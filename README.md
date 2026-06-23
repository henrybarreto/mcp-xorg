# mcp-xorg

MCP (Model Context Protocol) server that exposes a real, headless X11 desktop
as a set of remote-control tools: mouse, keyboard, screenshots, and process
launching.

It starts an [xpra](https://xpra.org/) `start-desktop` session on a free
display, then drives that display with
[pyautogui](https://pyautogui.readthedocs.io/) for input and screen capture.
Any MCP client can connect to it over stdio and call its tools.

## How it works

`xpra start-desktop` creates a real virtual X11 display (backed by Xvfb +
a window manager) and runs an app inside it. Unlike `xpra start` (seamless
mode, which only forwards individual app windows to remote clients and
never renders to the root window), `start-desktop` actually composites
windows onto the display's root window — so a plain X11 screenshot
(`pyautogui.screenshot()`) of that display shows real pixels.

Each server process owns at most one xpra session, on a display chosen at
startup. As soon as the session starts, the server's own `os.environ` is
updated with `DISPLAY` plus `XDG_SESSION_TYPE`/`GDK_BACKEND`/
`QT_QPA_PLATFORM`/`MOZ_ENABLE_WAYLAND` forced to X11, and `WAYLAND_DISPLAY`
is stripped — so pyautogui, imported in-process after the session starts,
targets the virtual session rather than the host's real (often Wayland)
desktop.

Processes started inside the session (the initial app and anything launched
via `launch_app`) get the same overrides applied to their own subprocess
environment. Without this, GTK/Qt/Chromium-based apps auto-detect a Wayland
session from the inherited environment and render on the host's real desktop
instead of the virtual one, regardless of `DISPLAY`.

## System requirements

- `xpra` (provides `start-desktop`)
- Optionally, an X11 app/window manager to launch on startup via `start_server`'s
  `app` argument. If omitted, the desktop starts with nothing running, which
  on most xpra installs shows a session chooser (e.g. "Openbox" / Start / Exit)
  until something is launched via `launch_app`.

On Arch/Manjaro: `sudo pacman -S xpra xterm`

## Setup

```bash
cd mcp-xorg
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `mcp-xorg` console script (`src/mcp_xorg/server.py:main`)
into the venv, which any MCP client launches as a stdio subprocess.

## Tools

- `start_server(app="xterm", width=1920, height=1080, force=False)` — start the desktop (also happens automatically on first use of any control tool)
- `stop_server()`
- `get_status()`
- `launch_app(command, focus=True, focus_delay=1.0)` — run another program inside the running session and click the screen center after `focus_delay` seconds to bring its window to the front (best-effort; unreliable if other windows already occupy the center)
- `view()` — attach a live xpra viewer window on the server host's own display, so an operator can watch/interact directly instead of relying on screenshots
- `screenshot()` — returns a PNG image of the current desktop
- `move_mouse(x, y, duration=0.0)`
- `click(x, y, button="left", clicks=1)`
- `double_click(x, y, button="left")`
- `drag(x, y, duration=0.5, button="left")`
- `scroll(amount, x=None, y=None)` — `amount` is wheel clicks, not pixels; small values (3–10) are usually enough for one page section
- `type_text(text, interval=0.0)`
- `press_key(key)`
- `hotkey(keys)` — e.g. `["ctrl", "c"]`

## Configuration (environment variables)

All read once at server startup (`src/mcp_xorg/config.py`):

| Env var | Purpose | Default |
|---|---|---|
| `XPRA_PATH` | path to the `xpra` binary | `xpra` (resolved via `$PATH`) |
| `XPRA_ATTACH` | auto-run `view()` right after `start_server` | `false` |
| `XPRA_DISPLAY` | pin to a fixed display number instead of picking randomly | unset → random |
| `XPRA_DISPLAY_RANGE` | `low-high` bounds for the random pick (ignored if `XPRA_DISPLAY` is set) | `100-999` |
| `XPRA_WIDTH` / `XPRA_HEIGHT` | default virtual screen resolution | `1920` / `1080` |
| `XPRA_EXTRA_ARGS` | extra raw args appended to `xpra start-desktop` (shell-quoted), e.g. `--opengl=yes` | empty |
| `PYAUTOGUI_PAUSE` | seconds pyautogui pauses after each action | `0.05` |
| `LOG_LEVEL` | Python logging level for the server's own logger (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |

`view()` attaches the viewer to whatever `DISPLAY` the server process itself
was launched with (captured as `HUMAN_DISPLAY` before the manager overwrites
`DISPLAY` with the virtual session's). If the server is launched with no
`DISPLAY` at all — the normal case on a headless host — `view()`/
`XPRA_ATTACH` will fail; `screenshot()` still works fine in that case.

## Logging

Session lifecycle events (start/stop/attach/launch) and failures are logged
via the standard `logging` module to **stderr** — never stdout, since stdout
carries the MCP stdio protocol. Set `LOG_LEVEL=DEBUG` for verbose output
(e.g. no-op `start_server` calls). Logging is only configured by `main()`;
if you embed `mcp_xorg.server` in another process, call
`logging.basicConfig(...)` yourself before use.

## Development

```bash
pip install -e ".[test]"
ruff check .
ruff format --check .
pytest
```

Dependencies are pinned for reproducible installs:
- `requirements-lock.txt` — runtime dependency closure
- `requirements-dev-lock.txt` — adds `pytest`/`pytest-cov`/`pytest-mock`/`ruff`

Regenerate after changing `pyproject.toml`'s dependencies:

```bash
pip install -e ".[test]" ruff
pip freeze --exclude-editable   # split output back into the two lock files
```

Tests mock all `subprocess`/`pyautogui` calls, so they don't need `xpra` or a
real X server installed — they run anywhere. CI (`.github/workflows/ci.yml`)
runs `ruff check`, `ruff format --check`, and `pytest` on every push and pull
request against `main`.

## Deployment

The server speaks MCP over stdio, so it has no listening network port of its
own; whatever process manager or MCP client launches it owns its lifecycle.
A minimal systemd user service:

```ini
# ~/.config/systemd/user/mcp-xorg.service
[Unit]
Description=mcp-xorg MCP server

[Service]
ExecStart=/path/to/mcp-xorg/.venv/bin/mcp-xorg
Environment=XPRA_WIDTH=1280
Environment=XPRA_HEIGHT=800
Restart=on-failure
```

Notes for running this unattended on a server:

- On a headless host (no `DISPLAY` in the service's environment), leave
  `XPRA_ATTACH` unset/`false` — there is no real desktop to attach a viewer
  to. `screenshot()` and all input tools still work; only `view()` is
  unavailable.
- `xpra`, `Xvfb`/`Xdummy`, and the default app (`xterm` or whatever
  `XPRA_DISPLAY`'s `app` resolves to) must be installed on the host image.
- The server tracks exactly one xpra session per process and does not
  reap it on its own; `stop_server()` (or process exit, since
  `--exit-with-client=no`/`--exit-with-children=no` keep the xpra server
  running independently) is the only way to tear it down. If the server
  process is killed without calling `stop_server()` first, the xpra process
  and its display socket are left running and need to be cleaned up
  separately (`xpra stop :N`).
- Pin `XPRA_DISPLAY` if you need a predictable, fixed display number instead
  of the default random pick from `XPRA_DISPLAY_RANGE`.
- Treat `launch_app`/`start_server`'s `app` argument as arbitrary shell
  command execution on the host — anything that can call this tool can run
  arbitrary commands inside (and, via `view()`, outside) the session. Don't
  expose this server to untrusted callers without a trust boundary in front
  of it.

## MCP client configuration

Any MCP client that supports stdio servers can launch this directly. Example
configuration (the exact file/format depends on the client):

```json
{
  "mcpServers": {
    "xorg": {
      "command": "/path/to/mcp-xorg/.venv/bin/mcp-xorg",
      "env": {
        "XPRA_ATTACH": "true",
        "XPRA_WIDTH": "1280",
        "XPRA_HEIGHT": "800"
      }
    }
  }
}
```

## Notes

- `pyautogui`'s X11 backend (via `mouseinfo`) opens its display connection
  using `os.environ["DISPLAY"]` as soon as it's imported. The server defers
  importing `pyautogui` until the xpra session has started and `DISPLAY`
  is set, so import order matters if you modify `server.py`.
- `pyautogui.FAILSAFE` is disabled since there's no physical mouse to yank
  to a screen corner.
- Only one xpra session is tracked per server process. Calling `start_server`
  again without `force=True` is a no-op that returns the existing session.
