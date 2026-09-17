import pytest
from packages.security.emergency import emergency_service
from packages.shared.database import init_db
from packages.shared.models import SkillExecutionStatus
from packages.skills.catalog import get_starter_skills
from packages.skills.engine import skill_engine
from packages.skills.registry import skill_registry
from packages.skills.schemas import SkillExecutionRequest


@pytest.fixture(autouse=True)
async def setup():
    await init_db()
    await emergency_service.resume(actor="TEST")


@pytest.mark.asyncio
async def test_end_to_end_canonical_skill_lifecycle():
    """Executes a real business skill through ToolGateway, verifying output and evidence."""
    # 1. Register canonical skill: research_business
    starter = [s for s in get_starter_skills() if s.skill_id == "research_business"][0]
    
    # Check if already registered
    existing = await skill_registry.get_skill_version(starter.skill_id, starter.version)
    if not existing:
        await skill_registry.register_skill(starter)
        await skill_registry.publish_skill(starter.skill_id, starter.version)

    # 2. Execute through SkillExecutionEngine
    req = SkillExecutionRequest(
        skill_id="research_business",
        version="1.0.0",
        input_data={
            "domain": "acmeflow.io",
            "business_name": "Acme Flow Automations",
            "pain_points": ["Manual invoice sync", "Slow lead response time"],
        },
    )
    result = await skill_engine.execute_skill(req)

    # 3. Assert verified completion
    assert result.status == SkillExecutionStatus.COMPLETED
    assert result.output is not None
    assert result.output.get("domain") == "acmeflow.io"
    assert "pain_points" in result.output
    assert result.evidence is not None
    assert result.duration_ms >= 0
