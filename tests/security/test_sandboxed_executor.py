"""Unit tests for SandboxedProcessExecutor.
Verifies environment secret stripping, execution timeout termination, and directory boundaries.
"""

import os
from pathlib import Path
import sys
import pytest

from packages.security.sandbox import SandboxedProcessExecutor, sandbox_executor


def test_environment_sanitization_strips_sensitive_keys(monkeypatch):
    """Verify all API keys, secrets, passwords, and tokens are stripped from the sandbox environment."""
    monkeypatch.setenv("DODO_API_KEY", "dodo_live_secret_key_12345")
    monkeypatch.setenv("APP_SECRET", "super_secret_app_key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "db_password_xyz")
    monkeypatch.setenv("NIM_API_KEY", "nvapi-secret123")
    monkeypatch.setenv("SAFE_TEST_VAR", "visible_value")

    sanitized = SandboxedProcessExecutor.get_sanitized_environment()

    assert "DODO_API_KEY" not in sanitized
    assert "APP_SECRET" not in sanitized
    assert "POSTGRES_PASSWORD" not in sanitized
    assert "NIM_API_KEY" not in sanitized
    assert sanitized.get("SAFE_TEST_VAR") == "visible_value"
    assert "PATH" in sanitized


def test_sync_command_execution(tmp_path):
    """Verify synchronous command runs within target directory and returns output."""
    test_script = tmp_path / "hello.py"
    test_script.write_text("print('SANBOX_OK')\n", encoding="utf-8")

    cmd = [sys.executable, str(test_script)]
    res = sandbox_executor.run_sync_command(cmd, cwd=tmp_path, timeout_seconds=10.0)

    assert res.success is True
    assert res.returncode == 0
    assert "SANBOX_OK" in res.stdout
    assert res.timed_out is False


def test_sync_command_timeout(tmp_path):
    """Verify long-running commands are terminated on timeout."""
    sleep_script = tmp_path / "sleep.py"
    sleep_script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")

    cmd = [sys.executable, str(sleep_script)]
    res = sandbox_executor.run_sync_command(cmd, cwd=tmp_path, timeout_seconds=1.0)

    assert res.success is False
    assert res.timed_out is True
    assert res.returncode == -2
    assert "timed out" in res.stderr.lower()


@pytest.mark.asyncio
async def test_async_command_execution(tmp_path):
    """Verify asynchronous execution within sandbox boundaries."""
    test_script = tmp_path / "async_test.py"
    test_script.write_text("import sys\nsys.stdout.write('ASYNC_OK')\n", encoding="utf-8")

    cmd = [sys.executable, str(test_script)]
    res = await sandbox_executor.run_async_command(cmd, cwd=tmp_path, timeout_seconds=10.0)

    assert res.success is True
    assert res.returncode == 0
    assert "ASYNC_OK" in res.stdout
