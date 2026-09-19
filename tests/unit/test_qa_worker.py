"""Unit tests for QAWorker verifying syntax, AST, and deliverable validation."""

import os
from pathlib import Path
import tempfile
import pytest
from packages.qa.worker import QAEvaluationRequest, qa_worker
from packages.shared.database import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_qa_worker_rejects_syntax_errors():
    """QA worker must fail Check 4 when deliverable has Python syntax errors."""
    workspace_dir = Path("workspace")
    workspace_dir.mkdir(exist_ok=True)
    broken_file = workspace_dir / "broken_script.py"

    broken_file.write_text("def invalid_syntax(\n    print('Missing closing parenthesis')\n", encoding="utf-8")

    req = QAEvaluationRequest(
        project_id="proj_qa_01",
        artifact_id="art_broken_01",
        artifact_path=str(broken_file),
        artifact_type="CODE",
        expected_criteria=["def invalid_syntax"],
    )

    try:
        res = await qa_worker.evaluate_deliverable(req)
        assert res.passed is False
        assert res.check4_functional_qa_valid is False
        assert any(f["category"] == "syntax_error" for f in res.findings)
    finally:
        if broken_file.exists():
            broken_file.unlink()


@pytest.mark.asyncio
async def test_qa_worker_passes_valid_code_and_criteria():
    """QA worker must pass valid Python deliverable without syntax errors or TODO markers."""
    workspace_dir = Path("workspace")
    workspace_dir.mkdir(exist_ok=True)
    valid_file = workspace_dir / "valid_script.py"

    valid_file.write_text(
        "def process_lead(lead_dict: dict) -> bool:\n    return bool(lead_dict.get('email'))\n",
        encoding="utf-8",
    )

    req = QAEvaluationRequest(
        project_id="proj_qa_02",
        artifact_id="art_valid_01",
        artifact_path=str(valid_file),
        artifact_type="CODE",
        expected_criteria=["process_lead"],
    )

    try:
        res = await qa_worker.evaluate_deliverable(req)
        assert res.passed is True
        assert res.check1_input_valid is True
        assert res.check2_security_policy_valid is True
        assert res.check3_execution_valid is True
        assert res.check4_functional_qa_valid is True
        assert res.check5_final_state_evidence_valid is True
        assert res.score == 1.0
    finally:
        if valid_file.exists():
            valid_file.unlink()
