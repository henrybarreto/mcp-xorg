"""Tests for mcp_xorg.manager.XpraManager."""

from __future__ import annotations

import os

import pytest

from mcp_xorg import config
from mcp_xorg.manager import SessionInfo, XpraError, XpraManager


@pytest.fixture(autouse=True)
def isolated_environ(mocker):
    """start()/stop() mutate os.environ in place; sandbox it for every test."""
    mocker.patch.dict(os.environ, {}, clear=False)


@pytest.fixture
def manager():
    return XpraManager(display_range=(100, 199))


@pytest.fixture
def run(mocker, completed_process):
    """subprocess.run as seen by mcp_xorg.manager, defaulting to success."""
    return mocker.patch("mcp_xorg.manager.subprocess.run", return_value=completed_process())


@pytest.fixture
def popen(mocker):
    return mocker.patch("mcp_xorg.manager.subprocess.Popen")


@pytest.fixture
def pinned_display(mocker):
    """Pin config.XPRA_DISPLAY so _pick_free_display() is deterministic."""

    def _pin(display: int):
        mocker.patch.object(config, "XPRA_DISPLAY", display)

    return _pin


class TestPickFreeDisplay:
    def test_uses_pinned_display(self, manager, pinned_display):
        pinned_display(555)
        assert manager._pick_free_display() == 555

    def test_picks_random_free_display(self, manager, mocker):
        mocker.patch.object(config, "XPRA_DISPLAY", None)
        mocker.patch("mcp_xorg.manager.os.path.exists", return_value=False)
        assert 100 <= manager._pick_free_display() <= 199

    def test_raises_when_no_free_display_found(self, manager, mocker):
        mocker.patch.object(config, "XPRA_DISPLAY", None)
        mocker.patch("mcp_xorg.manager.os.path.exists", return_value=True)
        with pytest.raises(XpraError, match="could not find a free X display"):
            manager._pick_free_display()


class TestStart:
    def test_success_returns_session_info(self, manager, pinned_display, run, mocker):
        pinned_display(200)
        mocker.patch.object(config, "XPRA_ATTACH", False)

        session = manager.start(app="xterm", width=800, height=600)

        assert session == SessionInfo(display=200, width=800, height=600, app="xterm")
        assert manager.session is session
        run.assert_called_once()
        cmd = run.call_args.args[0]
        assert cmd[0] == config.XPRA_PATH
        assert cmd[1] == "start-desktop"
        assert ":200" in cmd
        assert "--start=xterm" in cmd
        assert "--resize-display=800x600" in cmd

    def test_failure_raises_and_clears_session(
        self, manager, pinned_display, mocker, completed_process
    ):
        pinned_display(201)
        mocker.patch(
            "mcp_xorg.manager.subprocess.run",
            return_value=completed_process(1, stderr="boom"),
        )

        with pytest.raises(XpraError, match="boom"):
            manager.start()
        assert manager.session is None

    def test_noop_when_already_running_without_force(self, manager, pinned_display, run):
        pinned_display(202)
        first = manager.start()
        run.reset_mock()

        second = manager.start()

        assert second is first
        run.assert_not_called()

    def test_force_restarts_existing_session(self, manager, pinned_display, run):
        pinned_display(203)
        first = manager.start(app="xterm")

        pinned_display(204)
        second = manager.start(app="xclock", force=True)

        assert second != first
        assert second.app == "xclock"

    def test_applies_default_width_height_from_config(self, manager, pinned_display, run, mocker):
        pinned_display(205)
        mocker.patch.object(config, "XPRA_WIDTH", 1024)
        mocker.patch.object(config, "XPRA_HEIGHT", 768)

        session = manager.start()

        assert (session.width, session.height) == (1024, 768)

    def test_auto_attaches_when_configured(self, manager, pinned_display, run, popen, mocker):
        pinned_display(206)
        mocker.patch.object(config, "XPRA_ATTACH", True)
        mocker.patch.object(config, "HUMAN_DISPLAY", ":0")

        manager.start()

        popen.assert_called_once()


class TestIsRunning:
    def test_false_when_no_session(self, manager, run):
        assert manager.is_running() is False
        run.assert_not_called()

    def test_true_when_xpra_info_succeeds(self, manager, pinned_display, run):
        pinned_display(207)
        manager.start()
        assert manager.is_running() is True

    def test_false_when_xpra_info_fails(
        self, manager, pinned_display, run, mocker, completed_process
    ):
        pinned_display(208)
        manager.start()

        run.return_value = completed_process(1)
        assert manager.is_running() is False


class TestStop:
    def test_noop_when_no_session(self, manager, run):
        manager.stop()
        run.assert_not_called()

    def test_stops_session_and_terminates_viewer(self, manager, pinned_display, run, mocker):
        pinned_display(209)
        manager.start()
        fake_proc = mocker.Mock()
        manager._attach_proc = fake_proc
        run.reset_mock()

        manager.stop()

        fake_proc.terminate.assert_called_once()
        run.assert_called_once_with(
            [config.XPRA_PATH, "stop", ":209"], capture_output=True, text=True, timeout=15
        )
        assert manager.session is None
        assert manager._attach_proc is None


class TestAttach:
    def test_raises_when_no_session(self, manager):
        with pytest.raises(XpraError, match="no xpra session is running"):
            manager.attach()

    def test_raises_when_no_human_display(self, manager, pinned_display, run, mocker):
        pinned_display(210)
        mocker.patch.object(config, "HUMAN_DISPLAY", None)
        manager.start()

        with pytest.raises(XpraError, match="no DISPLAY was set"):
            manager.attach()

    def test_attaches_viewer(self, manager, pinned_display, run, popen, mocker):
        pinned_display(211)
        mocker.patch.object(config, "HUMAN_DISPLAY", ":0")
        manager.start()

        result = manager.attach()

        assert result == "attached viewer to :211 on :0"
        popen.assert_called_once()

    def test_returns_already_attached_when_viewer_alive(
        self, manager, pinned_display, run, popen, mocker
    ):
        pinned_display(212)
        mocker.patch.object(config, "HUMAN_DISPLAY", ":0")
        manager.start()
        fake_proc = mocker.Mock()
        fake_proc.poll.return_value = None
        manager._attach_proc = fake_proc

        result = manager.attach()

        assert "already attached" in result
        popen.assert_not_called()


class TestEnsureStarted:
    def test_starts_when_no_session(self, manager, pinned_display, run):
        pinned_display(213)
        assert manager.ensure_started().display_name == ":213"

    def test_returns_existing_session(self, manager, pinned_display, run):
        pinned_display(214)
        first = manager.start()
        assert manager.ensure_started() is first


class TestLaunchApp:
    def test_spawns_process_in_session_display(self, manager, pinned_display, run, mocker):
        pinned_display(215)
        manager.start()
        fake_proc = mocker.Mock(pid=4242)
        popen = mocker.patch("mcp_xorg.manager.subprocess.Popen", return_value=fake_proc)

        pid = manager.launch_app("xterm -e htop")

        assert pid == 4242
        assert popen.call_args.args[0] == "xterm -e htop"
        assert popen.call_args.kwargs["shell"] is True
        assert popen.call_args.kwargs["env"]["DISPLAY"] == ":215"


class TestSessionEnv:
    def test_x11_overrides_force_x11(self):
        overrides = XpraManager._x11_overrides(":99")
        assert overrides == {
            "DISPLAY": ":99",
            "XDG_SESSION_TYPE": "x11",
            "GDK_BACKEND": "x11",
            "QT_QPA_PLATFORM": "xcb",
            "MOZ_ENABLE_WAYLAND": "0",
        }

    def test_session_env_strips_wayland_display(self):
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        env = XpraManager._session_env(":99")
        assert "WAYLAND_DISPLAY" not in env
        assert env["DISPLAY"] == ":99"

    def test_apply_session_env_mutates_os_environ(self):
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        XpraManager._apply_session_env(":99")
        assert "WAYLAND_DISPLAY" not in os.environ
        assert os.environ["DISPLAY"] == ":99"


class TestSessionInfo:
    def test_display_name_formats_with_colon(self):
        assert SessionInfo(display=42, width=1, height=1, app=None).display_name == ":42"
