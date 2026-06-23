"""Lifecycle management for a single headless xpra desktop session."""

from __future__ import annotations

import logging
import os
import random
import subprocess
import threading
from dataclasses import dataclass

from mcp_xorg import config

logger = logging.getLogger(__name__)


class XpraError(RuntimeError):
    """Raised when an xpra subprocess invocation fails or is misused."""


@dataclass
class SessionInfo:
    """Metadata for one running xpra start-desktop session."""

    display: int
    width: int
    height: int
    app: str | None

    @property
    def display_name(self) -> str:
        """The session's display as an X11 display string, e.g. ':123'."""
        return f":{self.display}"


class XpraManager:
    """Owns at most one xpra start-desktop session for this process."""

    def __init__(self, display_range: tuple[int, int] | None = None) -> None:
        """display_range overrides config.XPRA_DISPLAY_RANGE for the random
        display picker; mainly useful for tests."""
        self._display_range = display_range or config.XPRA_DISPLAY_RANGE
        self._session: SessionInfo | None = None
        self._attach_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def session(self) -> SessionInfo | None:
        """The currently tracked session, or None if nothing was started."""
        return self._session

    def is_running(self) -> bool:
        """Whether the tracked session's xpra server is actually reachable."""
        if self._session is None:
            return False
        result = subprocess.run(
            [config.XPRA_PATH, "info", self._session.display_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0

    def _pick_free_display(self) -> int:
        """Return config.XPRA_DISPLAY if pinned, otherwise a display number
        with no existing X11 socket in the configured random range."""
        if config.XPRA_DISPLAY is not None:
            return config.XPRA_DISPLAY
        low, high = self._display_range
        for _ in range(100):
            candidate = random.randint(low, high)
            if not os.path.exists(f"/tmp/.X11-unix/X{candidate}"):
                return candidate
        raise XpraError("could not find a free X display after 100 attempts")

    def start(
        self,
        app: str | None = None,
        width: int | None = None,
        height: int | None = None,
        force: bool = False,
    ) -> SessionInfo:
        """Start (or return the existing) xpra start-desktop session.

        Raises XpraError if the xpra subprocess exits non-zero.
        """
        width = width or config.XPRA_WIDTH
        height = height or config.XPRA_HEIGHT
        with self._lock:
            if self._session is not None:
                if not force:
                    logger.debug(
                        "start() no-op: session already running on %s",
                        self._session.display_name,
                    )
                    return self._session
                logger.info("force-restarting xpra session on %s", self._session.display_name)
                self._stop_locked()

            display = self._pick_free_display()
            cmd = [
                config.XPRA_PATH,
                "start-desktop",
                f":{display}",
                "--daemon=yes",
                "--exit-with-children=no",
                "--exit-with-client=no",
                f"--resize-display={width}x{height}",
                "--no-pulseaudio",
                "--no-mdns",
                "--speaker=no",
                "--microphone=no",
                "--webcam=no",
                "--notifications=no",
                *config.XPRA_EXTRA_ARGS,
            ]
            if app:
                cmd.insert(3, f"--start={app}")
            env = self._session_env(f":{display}")
            logger.info(
                "starting xpra start-desktop on :%d (%dx%d, app=%r)", display, width, height, app
            )
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                error = result.stderr.strip() or result.stdout.strip()
                logger.error("xpra start-desktop failed (exit %d): %s", result.returncode, error)
                raise XpraError(f"xpra start-desktop failed (exit {result.returncode}): {error}")

            self._session = SessionInfo(display=display, width=width, height=height, app=app)
            self._apply_session_env(self._session.display_name)
            logger.info("xpra session started on %s", self._session.display_name)

            if config.XPRA_ATTACH:
                self._attach_locked()

            return self._session

    def stop(self) -> None:
        """Stop the tracked session and any attached viewer, if running."""
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        """stop() body; caller must hold self._lock."""
        if self._session is None:
            return
        display_name = self._session.display_name
        logger.info("stopping xpra session on %s", display_name)
        if self._attach_proc is not None:
            self._attach_proc.terminate()
            self._attach_proc = None
        result = subprocess.run(
            [config.XPRA_PATH, "stop", display_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning(
                "xpra stop on %s exited %d: %s",
                display_name,
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
        os.environ.pop("DISPLAY", None)
        self._session = None

    def attach(self) -> str:
        """Open a live viewer window on the human's real display, attached
        to the running xpra session."""
        with self._lock:
            if self._session is None:
                raise XpraError("no xpra session is running")
            return self._attach_locked()

    def _attach_locked(self) -> str:
        """attach() body; caller must hold self._lock."""
        if config.HUMAN_DISPLAY is None:
            raise XpraError(
                "no DISPLAY was set for this process; can't attach a viewer on the human's desktop"
            )
        if self._attach_proc is not None and self._attach_proc.poll() is None:
            return f"viewer already attached to {self._session.display_name}"

        env = {**os.environ, "DISPLAY": config.HUMAN_DISPLAY}
        self._attach_proc = subprocess.Popen(
            [config.XPRA_PATH, "attach", self._session.display_name],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("attached viewer to %s on %s", self._session.display_name, config.HUMAN_DISPLAY)
        return f"attached viewer to {self._session.display_name} on {config.HUMAN_DISPLAY}"

    def ensure_started(self) -> SessionInfo:
        """Return the running session, starting a blank desktop if needed."""
        if self._session is not None:
            return self._session
        return self.start()

    @staticmethod
    def _x11_overrides(display_name: str) -> dict[str, str]:
        """The env vars that force X11 (not Wayland) for a given display.
        Toolkits like GTK/Qt/Chromium auto-detect Wayland from these vars
        regardless of DISPLAY, so they must be forced to X11."""
        return {
            "DISPLAY": display_name,
            "XDG_SESSION_TYPE": "x11",
            "GDK_BACKEND": "x11",
            "QT_QPA_PLATFORM": "xcb",
            "MOZ_ENABLE_WAYLAND": "0",
        }

    @classmethod
    def _session_env(cls, display_name: str) -> dict[str, str]:
        """Environment for processes that must render into the virtual X11
        session, not the human's real (often Wayland) desktop."""
        env = dict(os.environ)
        env.pop("WAYLAND_DISPLAY", None)
        env.update(cls._x11_overrides(display_name))
        return env

    @classmethod
    def _apply_session_env(cls, display_name: str) -> None:
        """Mutate this process's own os.environ so that anything imported
        in-process (e.g. pyautogui) also targets the virtual X11 session
        instead of the human's real, possibly-Wayland, desktop."""
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.update(cls._x11_overrides(display_name))

    def launch_app(self, command: str) -> int:
        """Spawn an additional process inside the running session's display."""
        session = self.ensure_started()
        env = self._session_env(session.display_name)
        proc = subprocess.Popen(
            command,
            shell=True,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("launched %r on %s (pid %d)", command, session.display_name, proc.pid)
        return proc.pid
