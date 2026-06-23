"""Tests for the MCP tool functions in mcp_xorg.server.

manager.start()/stop() are exercised against the real XpraManager in
test_manager.py; here the manager is mocked entirely so each tool's own
glue logic (argument passing, error formatting, pyautogui calls) is what's
under test.
"""

from __future__ import annotations

import builtins

import pytest

from mcp_xorg import server
from mcp_xorg.manager import SessionInfo, XpraError


@pytest.fixture
def fake_manager(mocker):
    return mocker.patch.object(server, "manager")


@pytest.fixture
def fake_pyautogui(mocker):
    pyautogui = mocker.Mock()
    mocker.patch.object(server, "_ensure", return_value=pyautogui)
    return pyautogui


@pytest.fixture(autouse=True)
def isolated_pyautogui_cache():
    """_ensure() caches the imported pyautogui module on the server module itself."""
    pyautogui, display = server._pyautogui, server._pyautogui_display
    server._pyautogui, server._pyautogui_display = None, None
    yield
    server._pyautogui, server._pyautogui_display = pyautogui, display


@pytest.fixture
def fake_pyautogui_module(mocker):
    """Intercept `import pyautogui` inside _ensure() with a fake module.

    The real pyautogui package imports mouseinfo, which reads
    os.environ['DISPLAY'] at import time and raises on a headless CI
    runner with no X server. _ensure() is exercised here purely for its
    own caching logic, so the real package is never needed.
    """
    fake_module = mocker.MagicMock(name="pyautogui")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            return fake_module
        return real_import(name, *args, **kwargs)

    mocker.patch("builtins.__import__", side_effect=fake_import)
    return fake_module


def session(display=1, width=1, height=1, app=None) -> SessionInfo:
    return SessionInfo(display=display, width=width, height=height, app=app)


class TestEnsure:
    def test_imports_and_configures_pyautogui(self, fake_manager, fake_pyautogui_module):
        fake_manager.ensure_started.return_value = session(display=1)

        pyautogui = server._ensure()

        assert pyautogui.FAILSAFE is False
        assert server._pyautogui_display == ":1"

    def test_reuses_cached_module_for_same_display(self, fake_manager, fake_pyautogui_module):
        fake_manager.ensure_started.return_value = session(display=2)

        first = server._ensure()
        second = server._ensure()

        assert first is second

    def test_reimports_when_display_changes(self, fake_manager, fake_pyautogui_module):
        fake_manager.ensure_started.return_value = session(display=3)
        server._ensure()

        fake_manager.ensure_started.return_value = session(display=4)
        server._ensure()

        assert server._pyautogui_display == ":4"


class TestStartServer:
    def test_success_message(self, fake_manager):
        fake_manager.start.return_value = session(display=42, width=1920, height=1080, app="xterm")

        result = server.start_server(app="xterm")

        fake_manager.start.assert_called_once_with(
            app="xterm", width=None, height=None, force=False
        )
        assert result == "xpra desktop running on display :42 (1920x1080), started 'xterm'"

    def test_success_message_without_app(self, fake_manager):
        fake_manager.start.return_value = session(display=42, width=1920, height=1080)

        result = server.start_server()

        assert result == "xpra desktop running on display :42 (1920x1080)"

    def test_failure_message(self, fake_manager):
        fake_manager.start.side_effect = XpraError("xpra not installed")

        assert server.start_server() == "failed to start xpra: xpra not installed"


class TestStopServer:
    def test_stops_and_reports(self, fake_manager):
        assert server.stop_server() == "xpra session stopped"
        fake_manager.stop.assert_called_once()


class TestGetStatus:
    def test_no_session(self, fake_manager):
        fake_manager.session = None
        assert server.get_status() == "no xpra session running"

    def test_running_session(self, fake_manager):
        fake_manager.session = session(display=7, width=800, height=600, app="xterm")
        fake_manager.is_running.return_value = True

        result = server.get_status()

        assert result == "display=:7 resolution=800x600 app='xterm' running=True"


class TestLaunchApp:
    def test_launches_and_focuses(self, fake_manager, fake_pyautogui, mocker):
        mocker.patch("mcp_xorg.server.time.sleep")
        fake_manager.launch_app.return_value = 1234
        fake_pyautogui.size.return_value = (1920, 1080)

        result = server.launch_app("xterm -e htop", focus_delay=0)

        fake_manager.launch_app.assert_called_once_with("xterm -e htop")
        fake_pyautogui.click.assert_called_once_with(960, 540)
        assert result == "launched and focused 'xterm -e htop' (pid 1234)"

    def test_launches_without_focus(self, fake_manager, fake_pyautogui):
        fake_manager.launch_app.return_value = 5678

        result = server.launch_app("xclock", focus=False)

        fake_pyautogui.click.assert_not_called()
        assert result == "launched 'xclock' (pid 5678)"


class TestView:
    def test_attaches_viewer(self, fake_manager):
        fake_manager.attach.return_value = "attached viewer to :7 on :0"

        result = server.view()

        fake_manager.ensure_started.assert_called_once()
        assert result == "attached viewer to :7 on :0"

    def test_attach_failure_message(self, fake_manager):
        fake_manager.attach.side_effect = XpraError("no DISPLAY was set")

        assert server.view() == "failed to attach viewer: no DISPLAY was set"


class TestPyautoguiTools:
    def test_move_mouse(self, fake_pyautogui):
        result = server.move_mouse(10, 20, duration=0.5)
        fake_pyautogui.moveTo.assert_called_once_with(10, 20, duration=0.5)
        assert result == "moved mouse to (10, 20)"

    def test_click(self, fake_pyautogui):
        result = server.click(10, 20, button="right", clicks=2)
        fake_pyautogui.click.assert_called_once_with(x=10, y=20, clicks=2, button="right")
        assert result == "clicked (10, 20) button=right clicks=2"

    def test_double_click(self, fake_pyautogui):
        result = server.double_click(10, 20)
        fake_pyautogui.doubleClick.assert_called_once_with(x=10, y=20, button="left")
        assert result == "double-clicked (10, 20) button=left"

    def test_drag(self, fake_pyautogui):
        result = server.drag(10, 20, duration=1.0, button="middle")
        fake_pyautogui.dragTo.assert_called_once_with(10, 20, duration=1.0, button="middle")
        assert result == "dragged to (10, 20) button=middle"

    def test_scroll_with_coords(self, fake_pyautogui):
        result = server.scroll(5, x=1, y=2)
        fake_pyautogui.scroll.assert_called_once_with(5, x=1, y=2)
        assert result == "scrolled 5 at (1, 2)"

    def test_scroll_without_coords(self, fake_pyautogui):
        assert server.scroll(-5) == "scrolled -5"

    def test_type_text(self, fake_pyautogui):
        result = server.type_text("hello", interval=0.1)
        fake_pyautogui.write.assert_called_once_with("hello", interval=0.1)
        assert result == "typed 5 characters"

    def test_press_key(self, fake_pyautogui):
        result = server.press_key("enter")
        fake_pyautogui.press.assert_called_once_with("enter")
        assert result == "pressed 'enter'"

    def test_hotkey(self, fake_pyautogui):
        result = server.hotkey(["ctrl", "c"])
        fake_pyautogui.hotkey.assert_called_once_with("ctrl", "c")
        assert result == "pressed hotkey ctrl+c"


class TestScreenshot:
    def test_saves_and_returns_image(self, fake_pyautogui, mocker):
        image_cls = mocker.patch("mcp_xorg.server.Image")
        fake_img = mocker.Mock()
        fake_pyautogui.screenshot.return_value = fake_img

        server.screenshot()

        fake_img.save.assert_called_once()
        image_cls.assert_called_once()
        assert image_cls.call_args.kwargs["path"].endswith(".png")
