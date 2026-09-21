"""Adversarial QA Worker enforcing Five-Layer Verification.
Independently verifies worker deliverables, creates QARun and QAFinding records, and can reject deliverables.
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from packages.observability.logger import logger
from packages.observability.metrics import QA_EVALUATIONS_TOTAL, QA_FINDINGS_TOTAL
from packages.shared.database import async_session_factory
from packages.shared.models import QAFinding, QARun


class QAEvaluationRequest(BaseModel):
    project_id: str
    artifact_id: str
    run_id: Optional[str] = None
    artifact_path: str
    artifact_type: str  # CODE, N8N, MEDIA, REPORT
    expected_criteria: List[str] = Field(default_factory=list)


class FiveLayerVerificationResult(BaseModel):
    passed: bool
    score: float  # [0.0 - 1.0]
    check1_input_valid: bool
    check2_security_policy_valid: bool
    check3_execution_valid: bool
    check4_functional_qa_valid: bool
    check5_final_state_evidence_valid: bool
    findings: List[Dict[str, str]] = Field(default_factory=list)
    sha256_hash: Optional[str] = None


class QAWorker:
    """Independent adversarial evaluator of project artifacts."""

    async def evaluate_deliverable(
        self, req: QAEvaluationRequest
    ) -> FiveLayerVerificationResult:
        logger.info(f"QA Worker evaluating artifact {req.artifact_id} for project {req.project_id}")

        findings: List[Dict[str, str]] = []
        raw_p = Path(req.artifact_path)
        workspace_base = Path("workspace").resolve()
        artifacts_base = Path("artifacts").resolve()

        # Resolve path candidate relative to project sandbox or repo root if relative
        if raw_p.is_absolute():
            p = raw_p.resolve()
        else:
            safe_proj = "".join(c for c in req.project_id if c.isalnum() or c in ("-", "_")) if req.project_id else ""
            proj_sandbox = (workspace_base / "projects" / safe_proj).resolve() if safe_proj else workspace_base
            if (proj_sandbox / raw_p).exists():
                p = (proj_sandbox / raw_p).resolve()
            elif raw_p.exists():
                p = raw_p.resolve()
            else:
                p = (proj_sandbox / raw_p).resolve()

        # CHECK 1: Input & Schema Validation
        c1_valid = True
        if not req.artifact_path or not req.artifact_id or not req.project_id:
            c1_valid = False
            findings.append({
                "severity": "CRITICAL",
                "category": "schema_validation",
                "description": "Missing required metadata parameters for QA evaluation",
                "remediation": "Provide valid artifact_id and project_id",
            })

        # CHECK 2: Security & Policy Compliance
        c2_valid = True
        # Check for path traversal or leaked secrets in artifact
        is_sandbox_confined = False
        try:
            if ".." not in str(raw_p) and (p.is_relative_to(workspace_base) or p.is_relative_to(artifacts_base)):
                is_sandbox_confined = True
        except (ValueError, AttributeError):
            is_sandbox_confined = False

        if not is_sandbox_confined:
            c2_valid = False
            findings.append({
                "severity": "CRITICAL",
                "category": "security_violation",
                "description": "Artifact path escapes designated project sandbox",
                "remediation": "Confine all deliverables inside project workspace",
            })

        # CHECK 3: Execution Verification (File existence and non-zero bytes)
        c3_valid = True
        sha256 = None
        if not p.exists() or p.stat().st_size == 0:
            c3_valid = False
            findings.append({
                "severity": "CRITICAL",
                "category": "execution_failure",
                "description": f"Deliverable file '{req.artifact_path}' does not exist or has 0 bytes",
                "remediation": "Worker must regenerate artifact successfully before QA inspection",
            })
        else:
            try:
                content_bytes = p.read_bytes()
                sha256 = hashlib.sha256(content_bytes).hexdigest()
            except Exception as e:
                c3_valid = False
                findings.append({
                    "severity": "HIGH",
                    "category": "unreadable_file",
                    "description": f"Failed reading file bytes: {e}",
                    "remediation": "Ensure filesystem permissions permit reading",
                })

        # CHECK 4: Independent Functional QA (Criteria fulfillment)
        c4_valid = True
        if c3_valid:
            try:
                text_content = p.read_text(encoding="utf-8", errors="replace")
                # 4a. Check for unfinished placeholders
                placeholder_markers = ["TODO", "FIXME", "REPLACE_ME", "throw new Error('Not implemented')"]
                for marker in placeholder_markers:
                    if marker in text_content:
                        c4_valid = False
                        findings.append({
                            "severity": "HIGH",
                            "category": "incomplete_implementation",
                            "description": f"Artifact contains unfinished stub marker: '{marker}'",
                            "remediation": f"Remove {marker} and implement actual functional code/workflow",
                        })

                # 4b. Concrete Syntax & Parse Verification
                if p.suffix == ".py" or req.artifact_type == "CODE":
                    import ast
                    import py_compile
                    try:
                        ast.parse(text_content, filename=str(p))
                        py_compile.compile(str(p), doraise=True)
                    except SyntaxError as syn_err:
                        c4_valid = False
                        findings.append({
                            "severity": "CRITICAL",
                            "category": "syntax_error",
                            "description": f"Python syntax error at line {syn_err.lineno}: {syn_err.msg}",
                            "remediation": "Correct Python syntax error before submitting to QA",
                        })
                    except Exception as comp_err:
                        c4_valid = False
                        findings.append({
                            "severity": "HIGH",
                            "category": "compilation_failure",
                            "description": f"Compilation failed: {comp_err}",
                            "remediation": "Ensure code compiles cleanly without runtime parse errors",
                        })

                elif p.suffix == ".json" or req.artifact_type == "N8N":
                    import json
                    try:
                        parsed_json = json.loads(text_content)
                        if req.artifact_type == "N8N":
                            if not isinstance(parsed_json, dict) or "nodes" not in parsed_json:
                                c4_valid = False
                                findings.append({
                                    "severity": "HIGH",
                                    "category": "invalid_n8n_schema",
                                    "description": "JSON deliverable is missing top-level 'nodes' definition for n8n workflow",
                                    "remediation": "Structure JSON deliverable with valid n8n nodes and connections",
                                })
                    except json.JSONDecodeError as jde:
                        c4_valid = False
                        findings.append({
                            "severity": "CRITICAL",
                            "category": "json_parse_error",
                            "description": f"Invalid JSON syntax at line {jde.lineno}: {jde.msg}",
                            "remediation": "Fix invalid JSON formatting",
                        })

                # 4c. Validate expected criteria
                for crit in req.expected_criteria:
                    if crit.lower() not in text_content.lower():
                        c4_valid = False
                        findings.append({
                            "severity": "MEDIUM",
                            "category": "unmet_acceptance_criteria",
                            "description": f"Acceptance criterion '{crit}' is not reflected in artifact",
                            "remediation": f"Implement required criterion: {crit}",
                        })
            except Exception as ex:
                logger.error(f"Error during functional QA check: {ex}")
                findings.append({
                    "severity": "MEDIUM",
                    "category": "qa_inspection_error",
                    "description": f"Could not complete functional inspection: {str(ex)}",
                    "remediation": "Verify file integrity and accessibility",
                })

        # CHECK 5: Final State & Evidence
        c5_valid = c1_valid and c2_valid and c3_valid and (sha256 is not None)

        all_passed = c1_valid and c2_valid and c3_valid and c4_valid and c5_valid
        score = 1.0 if all_passed else max(0.0, 1.0 - (len(findings) * 0.25))

        # Authoritative persistence in Database
        await self._persist_qa_record(req, all_passed, score, findings)

        status_label = "passed" if all_passed else "failed"
        QA_EVALUATIONS_TOTAL.labels(status=status_label).inc()
        for f in findings:
            QA_FINDINGS_TOTAL.labels(severity=f["severity"]).inc()

        logger.info(
            f"QA Evaluation completed: passed={all_passed}, score={score:.2f}, findings={len(findings)}"
        )

        return FiveLayerVerificationResult(
            passed=all_passed,
            score=score,
            check1_input_valid=c1_valid,
            check2_security_policy_valid=c2_valid,
            check3_execution_valid=c3_valid,
            check4_functional_qa_valid=c4_valid,
            check5_final_state_evidence_valid=c5_valid,
            findings=findings,
            sha256_hash=sha256,
        )

    async def _persist_qa_record(
        self,
        req: QAEvaluationRequest,
        passed: bool,
        score: float,
        findings: List[Dict[str, str]],
    ) -> None:
        try:
            async with async_session_factory() as session:
                qa_run = QARun(
                    project_id=req.project_id,
                    artifact_id=req.artifact_id,
                    status="PASSED" if passed else "FAILED",
                    score=score,
                    notes=f"Five-layer verification completed. {len(findings)} findings.",
                )
                session.add(qa_run)
                await session.flush()

                for f in findings:
                    finding_rec = QAFinding(
                        qa_run_id=qa_run.id,
                        severity=f["severity"],
                        category=f["category"],
                        description=f["description"],
                        remediation=f["remediation"],
                        resolved=False,
                    )
                    session.add(finding_rec)

                await session.commit()
        except Exception as e:
            logger.error(f"Failed persisting QA run records: {e}")

    async def execute_sandbox_test(self, test_file_path: Path, timeout_seconds: float = 20.0) -> Tuple[bool, str]:
        """Executes a test file in an isolated Python subprocess without polluting the host or leaking secrets."""
        import sys
        if not test_file_path.exists():
            return False, f"Test file '{test_file_path}' does not exist"

        from packages.security.sandbox import sandbox_executor
        cmd = [sys.executable, "-m", "pytest", str(test_file_path), "-v"]
        res = await sandbox_executor.run_async_command(
            cmd,
            cwd=test_file_path.parent,
            timeout_seconds=timeout_seconds,
            additional_env={"PYTHONPATH": str(test_file_path.parent)},
        )
        if res.success:
            return True, res.stdout
        else:
            return False, res.stderr or res.stdout


# Global singleton
qa_worker = QAWorker()
