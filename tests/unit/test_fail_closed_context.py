"""Unit tests verifying fail-closed behavior when required runtime context is missing."""

import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.exceptions import MissingRequiredContextError
from packages.shared.models import FailureClassification, SkillExecutionStatus
from packages.skills.catalog import get_starter_skills
from packages.skills.engine import skill_engine
from packages.skills.registry import skill_registry
from packages.skills.schemas import ProcedureStep, SkillExecutionRequest


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    await emergency_service.resume(actor="TEST")


@pytest.mark.asyncio
async def test_skill_engine_fails_closed_when_domain_missing():
    """Skill execution must fail closed with schema validation error when domain is absent."""
    starter = [s for s in get_starter_skills() if s.skill_id == "research_business"][0]
    existing = await skill_registry.get_skill_version(starter.skill_id, starter.version)
    if not existing:
        await skill_registry.register_skill(starter)
        await skill_registry.publish_skill(starter.skill_id, starter.version)

    # Missing 'domain' - input_data only has irrelevant keys
    req = SkillExecutionRequest(
        skill_id="research_business",
        version="1.0.0",
        input_data={"some_unrelated_key": "val"},
    )
    result = await skill_engine.execute_skill(req)

    assert result.status == SkillExecutionStatus.FAILED
    assert "domain" in result.error
    assert result.failure_class == FailureClassification.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_transform_action_fails_closed_on_missing_domain():
    """Direct transform step must raise MissingRequiredContextError when domain is absent."""
    step = ProcedureStep(
        step_id="synthesize_findings",
        description="Synthesize findings",
        objective="Create output",
        action_type="TRANSFORM",
        expected_output="Done",
    )
    starter = [s for s in get_starter_skills() if s.skill_id == "research_business"][0]
    with pytest.raises(MissingRequiredContextError) as exc_info:
        skill_engine._execute_transform_action(
            step=step,
            skill=starter,
            input_data={"business_name": "Test Co"},
            accumulated_outputs={},
        )
    assert exc_info.value.missing_key == "domain"
    assert "synthesize_findings" in str(exc_info.value)


@pytest.mark.asyncio
async def test_transform_action_fails_closed_on_missing_proposal_fields():
    """Direct transform proposal step must raise MissingRequiredContextError when client_name or price is missing."""
    step = ProcedureStep(
        step_id="format_proposal",
        description="Format proposal",
        objective="Create proposal document",
        action_type="TRANSFORM",
        expected_output="Done",
    )
    starter = [s for s in get_starter_skills() if s.skill_id == "generate_client_proposal"][0]
    with pytest.raises(MissingRequiredContextError) as exc_info:
        skill_engine._execute_transform_action(
            step=step,
            skill=starter,
            input_data={"scope_summary": "Do automation", "price": 450.0},
            accumulated_outputs={},
        )
    assert exc_info.value.missing_key == "client_name"

    with pytest.raises(MissingRequiredContextError) as exc_info:
        skill_engine._execute_transform_action(
            step=step,
            skill=starter,
            input_data={"client_name": "Acme Corp", "scope_summary": "Do automation"},
            accumulated_outputs={},
        )
    assert exc_info.value.missing_key == "price"
