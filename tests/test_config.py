"""Tests for env-var parsing in mcp_xorg.config."""

from __future__ import annotations

import importlib
import os
from types import ModuleType

import pytest

from mcp_xorg import config


@pytest.fixture
def reload_config(mocker):
    """Let a test freely mutate os.environ, then reload mcp_xorg.config to
    re-parse it. pytest-mock's patch.dict snapshots os.environ on entry and
    restores it on teardown; the module is reloaded once more afterwards so
    later tests see config parsed from the real (restored) environment."""
    mocker.patch.dict(os.environ, {}, clear=False)

    def _reload() -> ModuleType:
        importlib.reload(config)
        return config

    yield _reload
    importlib.reload(config)


def test_bool_truthy_values():
    assert config._bool("1") is True
    assert config._bool("true") is True
    assert config._bool("Yes") is True
    assert config._bool(" on ") is True


def test_bool_falsy_values():
    assert config._bool("0") is False
    assert config._bool("false") is False
    assert config._bool("") is False
    assert config._bool("nonsense") is False


def test_parse_range_valid():
    assert config._parse_range("10-20", default=(1, 2)) == (10, 20)


@pytest.mark.parametrize("raw", ["", "garbage", "10", "10-"])
def test_parse_range_falls_back_to_default(raw):
    assert config._parse_range(raw, default=(1, 2)) == (1, 2)


def test_xpra_display_unset_is_none(reload_config):
    os.environ.pop("XPRA_DISPLAY", None)
    assert reload_config().XPRA_DISPLAY is None


def test_xpra_display_set_strips_colon(reload_config):
    os.environ["XPRA_DISPLAY"] = ":42"
    assert reload_config().XPRA_DISPLAY == 42


def test_xpra_display_range_default(reload_config):
    os.environ.pop("XPRA_DISPLAY_RANGE", None)
    assert reload_config().XPRA_DISPLAY_RANGE == (100, 999)


def test_xpra_display_range_custom(reload_config):
    os.environ["XPRA_DISPLAY_RANGE"] = "5-9"
    assert reload_config().XPRA_DISPLAY_RANGE == (5, 9)


def test_xpra_extra_args_shell_split(reload_config):
    os.environ["XPRA_EXTRA_ARGS"] = "--opengl=yes --foo 'bar baz'"
    assert reload_config().XPRA_EXTRA_ARGS == ["--opengl=yes", "--foo", "bar baz"]


def test_log_level_default(reload_config):
    os.environ.pop("LOG_LEVEL", None)
    assert reload_config().LOG_LEVEL == "INFO"


def test_log_level_normalized_uppercase(reload_config):
    os.environ["LOG_LEVEL"] = "debug"
    assert reload_config().LOG_LEVEL == "DEBUG"
