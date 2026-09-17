import uuid
import pytest
from sqlalchemy import select
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import SkillDefinition, SkillStatus, ToolRiskLevel
from packages.skills.registry import (
    SkillImmutabilityError,
    SkillNotFoundError,
    SkillRegistryError,
    SkillValidationError,
    skill_registry,
)
from packages.skills.schemas import (
    ProcedureStep,
    SkillDefinitionPayload,
    VerificationProcedure,
)


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


def make_test_skill_payload(skill_id_prefix: str = "test_data_extractor", version: str = "1.0.0") -> SkillDefinitionPayload:
    unique_id = f"{skill_id_prefix}_{uuid.uuid4().hex[:6]}"
    return SkillDefinitionPayload(
        skill_id=unique_id,
        name="Test Data Extractor",
        description="Extracts test data",
        category="TEST",
        purpose="Testing skill registry validation and lifecycles",
        version=version,
        input_schema={"type": "object", "required": ["source_url"], "properties": {"source_url": {"type": "string"}}},
        output_schema={"type": "object", "required": ["source_url"], "properties": {"source_url": {"type": "string"}}},
        allowed_tool_names=["filesystem.read", "filesystem.write"],
        procedure=[
            ProcedureStep(
                step_id="step_1",
                description="Read input source",
                objective="Assert file exists",
                action_type="OBSERVE",
                expected_output="source data loaded",
            )
        ],
        verification_procedure=VerificationProcedure(
            required_evidence_keys=["observed_at"],
        ),
        risk_class=ToolRiskLevel.LOW,
    )


@pytest.mark.asyncio
async def test_register_and_publish_skill_lifecycle():
    """Verify DRAFT -> VALIDATING -> PUBLISHED -> DEPRECATED transitions."""
    payload = make_test_skill_payload("lifecycle_skill", "1.0.0")
    s_id = payload.skill_id
    
    # 1. Register DRAFT
    skill = await skill_registry.register_skill(payload)
    assert skill.skill_id == s_id
    assert skill.version == "1.0.0"
    assert skill.status == SkillStatus.DRAFT

    # 2. Publish
    published = await skill_registry.publish_skill(s_id, "1.0.0")
    assert published.status == SkillStatus.PUBLISHED
    assert published.published_at is not None

    # 3. Resolve
    resolved = await skill_registry.resolve_compatible_skill(s_id)
    assert resolved.version == "1.0.0"

    # 4. Deprecate
    deprecated = await skill_registry.deprecate_skill(s_id, "1.0.0")
    assert deprecated.status == SkillStatus.DEPRECATED


@pytest.mark.asyncio
async def test_duplicate_skill_version_rejected_by_db_constraint():
    """Verify (skill_id, version) uniqueness."""
    payload = make_test_skill_payload("unique_skill", "1.0.0")
    await skill_registry.register_skill(payload)

    # Re-registering exact same version must fail
    with pytest.raises(SkillRegistryError):
        await skill_registry.register_skill(payload)


@pytest.mark.asyncio
async def test_published_skill_definition_immutability():
    """Verify database/ORM listener prevents altering published skill fields."""
    payload = make_test_skill_payload("immutable_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    # Attempt to directly mutate a published skill definition
    async with async_session_factory() as session:
        stmt = select(SkillDefinition).where(
            SkillDefinition.skill_id == s_id,
            SkillDefinition.version == "1.0.0",
        )
        sk = (await session.execute(stmt)).scalar_one()
        sk.description = "Altered description attempting to violate immutability"
        
        with pytest.raises(ValueError, match="SkillImmutabilityViolation"):
            await session.commit()


@pytest.mark.asyncio
async def test_invalid_semantic_version_and_unknown_tool_rejection():
    """Verify rejection of invalid semver and unregistered tools."""
    # 1. Bad SemVer
    with pytest.raises(ValueError, match="strictly follow Semantic Versioning"):
        make_test_skill_payload("bad_semver", "v1.0")

    # 2. Unknown Tool
    payload_bad_tool = make_test_skill_payload("bad_tool_skill", "1.0.0")
    payload_bad_tool.allowed_tool_names = ["non_existent_dangerous_tool"]
    payload_bad_tool.procedure[0].allowed_tools = ["non_existent_dangerous_tool"]
    
    with pytest.raises(SkillValidationError, match="not registered in ToolGateway"):
        await skill_registry.register_skill(payload_bad_tool)


@pytest.mark.asyncio
async def test_published_skill_cannot_be_demoted_to_draft_or_validating():
    """Verify that a skill that has reached PUBLISHED cannot be demoted to DRAFT or VALIDATING."""
    payload = make_test_skill_payload("no_demote_skill", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    # 1. Attempt to demote PUBLISHED -> DRAFT
    async with async_session_factory() as session:
        stmt = select(SkillDefinition).where(
            SkillDefinition.skill_id == s_id,
            SkillDefinition.version == "1.0.0",
        )
        sk = (await session.execute(stmt)).scalar_one()
        sk.status = SkillStatus.DRAFT

        with pytest.raises(ValueError, match="SkillImmutabilityViolation: Cannot transition published skill.*to 'DRAFT'"):
            await session.commit()

    # 2. Attempt to demote PUBLISHED -> VALIDATING
    async with async_session_factory() as session:
        stmt = select(SkillDefinition).where(
            SkillDefinition.skill_id == s_id,
            SkillDefinition.version == "1.0.0",
        )
        sk = (await session.execute(stmt)).scalar_one()
        sk.status = SkillStatus.VALIDATING

        with pytest.raises(ValueError, match="SkillImmutabilityViolation: Cannot transition published skill.*to 'VALIDATING'"):
            await session.commit()


@pytest.mark.asyncio
async def test_published_skill_allowed_transitions():
    """Verify legitimate PUBLISHED -> DEPRECATED and PUBLISHED -> DISABLED transitions succeed."""
    # 1. Test transition to DEPRECATED
    payload_dep = make_test_skill_payload("allow_dep_skill", "1.0.0")
    s_id_dep = payload_dep.skill_id
    await skill_registry.register_skill(payload_dep)
    await skill_registry.publish_skill(s_id_dep, "1.0.0")

    dep = await skill_registry.deprecate_skill(s_id_dep, "1.0.0")
    assert dep.status == SkillStatus.DEPRECATED
    assert dep.deprecated_at is not None

    # 2. Test transition to DISABLED
    payload_dis = make_test_skill_payload("allow_dis_skill", "1.0.0")
    s_id_dis = payload_dis.skill_id
    await skill_registry.register_skill(payload_dis)
    await skill_registry.publish_skill(s_id_dis, "1.0.0")

    dis = await skill_registry.disable_skill(s_id_dis, "1.0.0")
    assert dis.status == SkillStatus.DISABLED


@pytest.mark.asyncio
@pytest.mark.parametrize("field_name, new_value", [
    ("estimated_effort", 5.5),
    ("expected_duration_seconds", 3600),
    ("cost_estimate", 12.50),
    ("reusable_components", [{"component_id": "new_comp", "type": "script"}]),
    ("name", "Renamed Published Skill"),
    ("input_schema", {"type": "object", "properties": {"new_field": {"type": "string"}}}),
    ("allowed_tool_names", ["filesystem.read"]),
])
async def test_published_skill_immutable_fields_enforcement(field_name, new_value):
    """Verify that newly protected estimation/component fields and core definition fields cannot be altered once PUBLISHED."""
    payload = make_test_skill_payload(f"imm_{field_name}", "1.0.0")
    s_id = payload.skill_id
    await skill_registry.register_skill(payload)
    await skill_registry.publish_skill(s_id, "1.0.0")

    async with async_session_factory() as session:
        stmt = select(SkillDefinition).where(
            SkillDefinition.skill_id == s_id,
            SkillDefinition.version == "1.0.0",
        )
        sk = (await session.execute(stmt)).scalar_one()
        setattr(sk, field_name, new_value)

        with pytest.raises(ValueError, match=f"SkillImmutabilityViolation: Cannot mutate '{field_name}' of published skill"):
            await session.commit()

