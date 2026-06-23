"""Shared fixtures for the mcp_xorg test suite."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest


@pytest.fixture
def completed_process() -> Callable[..., subprocess.CompletedProcess]:
    """Factory for a fake subprocess.CompletedProcess, for mocking subprocess.run."""

    def _make(
        returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _make
