"""MCP server that drives a headless xpra X11 desktop via pyautogui."""

from __future__ import annotations

import logging
import sys
import tempfile
import time

from mcp.server.fastmcp import FastMCP, Image

from mcp_xorg import config
from mcp_xorg.manager import XpraError, XpraManager

logger = logging.getLogger(__name__)

mcp = FastMCP("xorg")
manager = XpraManager()

_pyautogui = None
_pyautogui_display: str | None = None


def _ensure():
    """Auto-start the xpra session on first use of a control tool.

    pyautogui opens its X11 connection once, at import time, against
    whatever os.environ['DISPLAY'] is at that moment, and never
    reconnects. If the xpra session is stopped and a new one started on a
    different display, the cached connection is left pointing at a dead
    server, so we force a fresh import whenever the active display
    changes.
    """
    global _pyautogui, _pyautogui_display
    session = manager.ensure_started()
    if _pyautogui is None or _pyautogui_display != session.display_name:
        for name in list(sys.modules):
            if name == "pyautogui" or name.startswith("pyautogui."):
                del sys.modules[name]
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = config.PYAUTOGUI_PAUSE
        _pyautogui = pyautogui
        _pyautogui_display = session.display_name
    return _pyautogui


@mcp.tool()
def start_server(
    app: str | None = None,
    width: int | None = None,
    height: int | None = None,
    force: bool = False,
) -> str:
    """Start the xpra virtual desktop on a random free display.

    If a session is already running this is a no-op unless force=True,
    in which case the existing session is stopped and a new one started.

    Args:
        app: command to launch inside the new desktop. If omitted, the
            desktop starts with no application running.
        width: virtual screen width in pixels (defaults to XPRA_WIDTH config).
        height: virtual screen height in pixels (defaults to XPRA_HEIGHT config).
        force: stop any existing session and start a fresh one.
    """
    try:
        session = manager.start(app=app, width=width, height=height, force=force)
    except XpraError as exc:
        logger.error("start_server failed: %s", exc)
        return f"failed to start xpra: {exc}"
    started = f", started '{session.app}'" if session.app else ""
    return (
        f"xpra desktop running on display {session.display_name} "
        f"({session.width}x{session.height}){started}"
    )


@mcp.tool()
def stop_server() -> str:
    """Stop the running xpra session, if any."""
    manager.stop()
    return "xpra session stopped"


@mcp.tool()
def get_status() -> str:
    """Report whether an xpra session is running and its display/resolution."""
    session = manager.session
    if session is None:
        return "no xpra session running"
    running = manager.is_running()
    return (
        f"display={session.display_name} resolution={session.width}x{session.height} "
        f"app='{session.app or ''}' running={running}"
    )


@mcp.tool()
def launch_app(command: str, focus: bool = True, focus_delay: float = 1.0) -> str:
    """Launch an additional program inside the running xpra desktop and
    bring its window to the front by clicking it.

    Auto-starts a blank desktop if nothing is running yet.
    Focusing is a best-effort click on the screen center after a delay, since
    a freshly launched window is most commonly the topmost/centered one; it
    isn't reliable if other windows already occupy that spot.

    Args:
        command: shell command to run, e.g. "firefox" or "xterm -e htop".
        focus: click the screen center after launch to focus the new window.
        focus_delay: seconds to wait for the window to appear before clicking.
    """
    pyautogui = _ensure()
    pid = manager.launch_app(command)
    if focus:
        time.sleep(focus_delay)
        width, height = pyautogui.size()
        pyautogui.click(width // 2, height // 2)
    status = "launched and focused" if focus else "launched"
    return f"{status} '{command}' (pid {pid})"


@mcp.tool()
def view() -> str:
    """Open a live xpra viewer window on the human's real desktop, attached
    to the running session, so a person can watch (and interact with) it
    directly instead of relying on screenshots. Auto-starts the desktop
    if nothing is running yet."""
    manager.ensure_started()
    try:
        return manager.attach()
    except XpraError as exc:
        logger.error("view failed: %s", exc)
        return f"failed to attach viewer: {exc}"


@mcp.tool()
def screenshot() -> Image:
    """Capture the current contents of the xpra desktop as a PNG image."""
    pyautogui = _ensure()
    img = pyautogui.screenshot()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f.name)
        return Image(path=f.name)


@mcp.tool()
def move_mouse(x: int, y: int, duration: float = 0.0) -> str:
    """Move the mouse cursor to absolute coordinates (x, y)."""
    pyautogui = _ensure()
    pyautogui.moveTo(x, y, duration=duration)
    return f"moved mouse to ({x}, {y})"


@mcp.tool()
def click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    """Click the mouse at absolute coordinates (x, y).

    Args:
        x: target x coordinate.
        y: target y coordinate.
        button: "left", "right", or "middle".
        clicks: number of clicks to perform (e.g. 2 for double-click).
    """
    pyautogui = _ensure()
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    return f"clicked ({x}, {y}) button={button} clicks={clicks}"


@mcp.tool()
def double_click(x: int, y: int, button: str = "left") -> str:
    """Double-click the mouse at absolute coordinates (x, y)."""
    pyautogui = _ensure()
    pyautogui.doubleClick(x=x, y=y, button=button)
    return f"double-clicked ({x}, {y}) button={button}"


@mcp.tool()
def drag(x: int, y: int, duration: float = 0.5, button: str = "left") -> str:
    """Drag the mouse from its current position to absolute coordinates (x, y)."""
    pyautogui = _ensure()
    pyautogui.dragTo(x, y, duration=duration, button=button)
    return f"dragged to ({x}, {y}) button={button}"


@mcp.tool()
def scroll(amount: int, x: int | None = None, y: int | None = None) -> str:
    """Scroll the mouse wheel. Positive amount scrolls up, negative scrolls down.

    Args:
        amount: scroll amount/direction.
        x: optional x coordinate to move to before scrolling.
        y: optional y coordinate to move to before scrolling.
    """
    pyautogui = _ensure()
    pyautogui.scroll(amount, x=x, y=y)
    return f"scrolled {amount}" + (f" at ({x}, {y})" if x is not None else "")


@mcp.tool()
def type_text(text: str, interval: float = 0.0) -> str:
    """Type text using the virtual keyboard.

    Args:
        text: the text to type.
        interval: seconds to wait between keystrokes.
    """
    pyautogui = _ensure()
    pyautogui.write(text, interval=interval)
    return f"typed {len(text)} characters"


@mcp.tool()
def press_key(key: str) -> str:
    """Press and release a single key (e.g. "enter", "esc", "tab", "f5")."""
    pyautogui = _ensure()
    pyautogui.press(key)
    return f"pressed '{key}'"


@mcp.tool()
def hotkey(keys: list[str]) -> str:
    """Press a combination of keys together, e.g. ["ctrl", "c"]."""
    pyautogui = _ensure()
    pyautogui.hotkey(*keys)
    return f"pressed hotkey {'+'.join(keys)}"


def main() -> None:
    """Entry point for the `mcp-xorg` console script; runs the stdio MCP server."""
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
