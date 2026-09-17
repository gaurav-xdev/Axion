import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import FailureClassification, SkillActionType, SkillExecutionStatus
from packages.skills.engine import skill_engine
from packages.skills.registry import SkillValidationError, skill_registry
from packages.skills.schemas import SkillExecutionRequest
from tests.unit.test_skill_registry import make_test_skill_payload


@pytest.fixture(autouse=True)
async def setup():
    await init_db()
    await emergency_service.resume(actor="TEST")


@pytest.mark.asyncio
async def test_tool_restriction_violator_is_blocked():
    """Verify engine blocks a step trying to execute a tool not in skill.allowed_tool_names."""
    payload = make_test_skill_payload("restrict_tool_skill", "1.0.0")
    payload.allowed_tool_names = ["filesystem.read", "filesystem.write"]
    payload.procedure[0].action_type = SkillActionType.TOOL_CALL
    payload.procedure[0].allowed_tools = ["filesystem.write"]

    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(payload.skill_id, "1.0.0")

    # Verify that if a skill has allowed_tool_names restricted, unallowed tools are rejected during validation
    bad_payload = make_test_skill_payload("bad_tool_proc", "1.0.0")
    bad_payload.allowed_tool_names = ["filesystem.read"]
    bad_payload.procedure[0].action_type = SkillActionType.TOOL_CALL
    bad_payload.procedure[0].allowed_tools = ["filesystem.write"]  # Not in allowed_tool_names

    with pytest.raises(SkillValidationError, match="not declared in allowed_tool_names"):
        await skill_registry.register_skill(bad_payload)


@pytest.mark.asyncio
async def test_emergency_stop_blocks_skill_execution():
    """Verify Emergency STOP completely prevents skill execution."""
    payload = make_test_skill_payload("stop_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    # Trip Emergency STOP
    await emergency_service.stop(actor="TEST", reason="Security anomaly detected")

    req = SkillExecutionRequest(
        skill_id=s_id,
        version="1.0.0",
        input_data={"source_url": "https://example.com/test"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "Emergency STOP" in result.error
    assert result.failure_class == FailureClassification.EMERGENCY_STOP


@pytest.mark.asyncio
async def test_disabled_skill_cannot_be_executed():
    """Verify DISABLED skills reject execution requests."""
    payload = make_test_skill_payload("disabled_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")
    await skill_registry.disable_skill(s_id, "1.0.0")

    req = SkillExecutionRequest(
        skill_id=s_id,
        version="1.0.0",
        input_data={"source_url": "https://example.com/test"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.FAILED
    assert "DISABLED" in result.error
