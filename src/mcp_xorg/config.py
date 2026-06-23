"""Environment-variable configuration for mcp-xorg, read once at import time."""

from __future__ import annotations

import os
import shlex


def _bool(value: str) -> bool:
    """Parse a truthy env var string ("1"/"true"/"yes"/"on", case-insensitive)."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_range(value: str, default: tuple[int, int]) -> tuple[int, int]:
    """Parse a "low-high" env var string, falling back to default if unset/invalid."""
    try:
        low, high = value.split("-", 1)
        return int(low), int(high)
    except (ValueError, AttributeError):
        return default


XPRA_PATH: str = os.environ.get("XPRA_PATH", "xpra")
XPRA_ATTACH: bool = _bool(os.environ.get("XPRA_ATTACH", "false"))

_raw_display = os.environ.get("XPRA_DISPLAY", "").strip()
XPRA_DISPLAY: int | None = int(_raw_display.lstrip(":")) if _raw_display else None

XPRA_DISPLAY_RANGE: tuple[int, int] = _parse_range(
    os.environ.get("XPRA_DISPLAY_RANGE", ""), default=(100, 999)
)

XPRA_WIDTH: int = int(os.environ.get("XPRA_WIDTH", "1920"))
XPRA_HEIGHT: int = int(os.environ.get("XPRA_HEIGHT", "1080"))

XPRA_EXTRA_ARGS: list[str] = shlex.split(os.environ.get("XPRA_EXTRA_ARGS", ""))

PYAUTOGUI_PAUSE: float = float(os.environ.get("PYAUTOGUI_PAUSE", "0.05"))

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

# The real, human-facing DISPLAY this process was launched with (used to attach
# a viewer back to the user's own desktop). Captured before XpraManager starts
# overwriting os.environ["DISPLAY"] with the virtual session's display.
HUMAN_DISPLAY: str | None = os.environ.get("DISPLAY")
