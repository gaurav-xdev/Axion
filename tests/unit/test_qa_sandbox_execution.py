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
