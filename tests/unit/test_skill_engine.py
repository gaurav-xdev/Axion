import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import FailureClassification, SkillExecutionStatus
from packages.skills.engine import skill_engine
from packages.skills.registry import skill_registry
from packages.skills.schemas import SkillExecutionRequest
from tests.unit.test_skill_registry import make_test_skill_payload


@pytest.fixture(autouse=True)
async def setup():
    await init_db()
    await emergency_service.resume(actor="TEST")


@pytest.mark.asyncio
async def test_skill_execution_success_and_metrics():
    """Verify standard valid skill execution, evidence gathering, and atomic metrics."""
    payload = make_test_skill_payload("exec_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    req = SkillExecutionRequest(
        skill_id=s_id,
        version="1.0.0",
        input_data={"source_url": "https://example.com/test"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.COMPLETED
    assert result.error is None
    assert result.evidence is not None
    assert "observed_at" in str(result.evidence)


@pytest.mark.asyncio
async def test_skill_execution_paused_semantics():
    """Verify that when system is PAUSED, new executions are held in WAITING and no side-effects occur."""
    payload = make_test_skill_payload("paused_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    # Put system in PAUSED state
    await emergency_service.pause(actor="TEST", reason="Routine operator audit")

    req = SkillExecutionRequest(
        skill_id=s_id,
        version="1.0.0",
        input_data={"source_url": "https://example.com/test"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.WAITING
    assert "PAUSED" in result.error
    assert result.failure_class == FailureClassification.POLICY_BLOCK


@pytest.mark.asyncio
async def test_skill_execution_input_validation_failure():
    """Verify input schema mismatch rejects execution immediately."""
    payload = make_test_skill_payload("schema_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    # Missing required 'source_url'
    req = SkillExecutionRequest(
        skill_id=s_id,
        version="1.0.0",
        input_data={"invalid_key": "some_data"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.FAILED
    assert "Input schema validation failed" in result.error
    assert result.failure_class == FailureClassification.VALIDATION_ERROR
