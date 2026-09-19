"""Unit tests verifying exhaustive SkillActionType handling and rejection of unsupported actions."""

import uuid
import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import FailureClassification, SkillExecutionStatus, ToolRiskLevel
from packages.skills.engine import skill_engine
from packages.skills.registry import skill_registry
from packages.skills.schemas import (
    ProcedureStep,
    SkillDefinitionPayload,
    SkillExecutionRequest,
    VerificationProcedure,
)


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    await emergency_service.resume(actor="TEST")


@pytest.mark.asyncio
async def test_skill_actions_plan_decide_report_execution():
    """Verify PLAN, DECIDE, and REPORT action types execute and produce structured outputs."""
    uid = uuid.uuid4().hex[:6]
    payload = SkillDefinitionPayload(
        skill_id=f"lifecycle_actions_{uid}",
        name="Lifecycle Actions Skill",
        description="Tests plan decide and report actions",
        category="ANALYSIS",
        purpose="Test action exhaustiveness",
        version="1.0.0",
        input_schema={"type": "object", "properties": {"project_name": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"step_id": {"type": "string"}}},
        allowed_tool_names=[],
        procedure=[
            ProcedureStep(
                step_id="plan_step",
                description="Decompose project requirements",
                objective="Create structured task plan",
                action_type="PLAN",
                expected_output="Task plan created",
            ),
            ProcedureStep(
                step_id="decide_step",
                description="Evaluate feasibility",
                objective="Decide proceed or abort",
                action_type="DECIDE",
                expected_output="Decision rendered",
            ),
            ProcedureStep(
                step_id="report_step",
                description="Summarize execution report",
                objective="Emit final report",
                action_type="REPORT",
                expected_output="Report completed",
            ),
        ],
        verification_procedure=VerificationProcedure(
            required_evidence_keys=[],
        ),
        risk_class=ToolRiskLevel.LOW,
    )
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(payload.skill_id, "1.0.0")

    req = SkillExecutionRequest(
        skill_id=payload.skill_id,
        version="1.0.0",
        input_data={"project_name": "Test Action Plan"},
    )
    res = await skill_engine.execute_skill(req)

    assert res.status == SkillExecutionStatus.COMPLETED
    assert res.output is not None
    assert res.output.get("step_id") == "report_step"
    assert "reported_step" in res.evidence.get("report_step", {})


@pytest.mark.asyncio
async def test_unsupported_action_type_fails_closed():
    """Verify any invalid or unsupported action type fails closed with policy block."""
    uid = uuid.uuid4().hex[:6]
    step = ProcedureStep(
        step_id="unsupported_step",
        description="Execute unknown hardware command",
        objective="Unknown",
        action_type="OBSERVE",
        expected_output="Nothing",
    )
    step.action_type = "FLY_SPACESHIP"  # dynamically override

    payload = SkillDefinitionPayload(
        skill_id=f"unsupported_skill_{uid}",
        name="Unsupported Skill",
        description="Tests unsupported action rejection",
        category="ANALYSIS",
        purpose="Test fail closed",
        version="1.0.0",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        allowed_tool_names=[],
        procedure=[step],
        verification_procedure=VerificationProcedure(
            required_evidence_keys=[],
        ),
        risk_class=ToolRiskLevel.LOW,
    )

    from packages.shared.exceptions import UnsupportedActionError
    with pytest.raises(UnsupportedActionError) as exc_info:
        await skill_engine._execute_procedure_step(
            step=step,
            skill=payload,
            execution_id="test_exec",
            project_id=None,
            task_id=None,
            input_data={},
            accumulated_outputs={},
            actor_role="TEST",
            timeout_seconds=10,
        )
    assert "FLY_SPACESHIP" in str(exc_info.value)
