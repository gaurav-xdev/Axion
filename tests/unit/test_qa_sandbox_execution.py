"""Unit tests for QAWorker sandbox test execution runner."""

from pathlib import Path
import pytest
from packages.qa.worker import qa_worker


@pytest.mark.asyncio
async def test_qa_worker_sandbox_test_success(tmp_path):
    """Verify execute_sandbox_test runs a valid pytest script and reports success."""
    test_file = tmp_path / "test_sample_valid.py"
    test_file.write_text(
        "def test_arithmetic():\n"
        "    assert 2 + 2 == 4\n"
    )

    passed, output = await qa_worker.execute_sandbox_test(test_file, timeout_seconds=10.0)
    assert passed is True
    assert "1 passed" in output or "PASSED" in output


@pytest.mark.asyncio
async def test_qa_worker_sandbox_test_failure(tmp_path):
    """Verify execute_sandbox_test catches failing assertions in deliverables."""
    test_file = tmp_path / "test_sample_failing.py"
    test_file.write_text(
        "def test_failing_logic():\n"
        "    assert 10 == 99\n"
    )

    passed, output = await qa_worker.execute_sandbox_test(test_file, timeout_seconds=10.0)
    assert passed is False
    assert "AssertionError" in output or "FAILED" in output


@pytest.mark.asyncio
async def test_qa_worker_sandbox_sanitizes_environment(tmp_path, monkeypatch):
    """Verify execute_sandbox_test does not leak sensitive credentials into the subprocess."""
    monkeypatch.setenv("DODO_API_KEY", "super_secret_dodo_key")
    monkeypatch.setenv("APP_SECRET", "super_secret_app_secret")

    test_file = tmp_path / "test_env_leak.py"
    test_file.write_text(
        "import os\n"
        "def test_no_secrets():\n"
        "    assert 'DODO_API_KEY' not in os.environ\n"
        "    assert 'APP_SECRET' not in os.environ\n"
    )

    passed, output = await qa_worker.execute_sandbox_test(test_file, timeout_seconds=10.0)
    assert passed is True, f"Secrets leaked into sandbox subprocess: {output}"
