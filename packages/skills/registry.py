"""Central Skill Registry Service.
Handles registration, semantic version resolution, validation, publication, immutability,
and lifecycle state transitions for all agent skills.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import desc, select, update
from sqlalchemy.exc import IntegrityError

from packages.observability.logger import logger
from packages.security.redaction import redact_dict
from packages.shared.database import async_session_factory
from packages.shared.models import (
    AuditEvent,
    SkillDefinition,
    SkillMetrics,
    SkillStatus,
    ToolRiskLevel,
)
from packages.skills.schemas import SEMVER_REGEX, SkillDefinitionPayload
from packages.tools.gateway import tool_gateway


def parse_semver(v: str) -> Tuple[int, int, int]:
    match = SEMVER_REGEX.match(v)
    if not match:
        raise ValueError(f"Invalid semver: {v}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


class SkillRegistryError(Exception):
    pass


class SkillValidationError(SkillRegistryError):
    pass


class SkillNotFoundError(SkillRegistryError):
    pass


class SkillImmutabilityError(SkillRegistryError):
    pass


class SkillRegistry:
    """Authoritative registry for versioned skills."""

    async def register_skill(self, payload: SkillDefinitionPayload, actor: str = "OPERATOR") -> SkillDefinition:
        """Registers a new skill definition in DRAFT status."""
        # Validate structure and rules
        validation = await self.validate_skill_payload(payload)
        if not validation["valid"]:
            raise SkillValidationError(f"Skill validation failed: {validation['errors']}")

        async with async_session_factory() as session:
            # Check unique constraint at query time before insert
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == payload.skill_id,
                SkillDefinition.version == payload.version,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                raise SkillRegistryError(
                    f"Skill '{payload.skill_id}' v{payload.version} already exists."
                )

            skill = SkillDefinition(
                skill_id=payload.skill_id,
                name=payload.name,
                description=payload.description,
                category=payload.category,
                purpose=payload.purpose,
                version=payload.version,
                status=SkillStatus.DRAFT,
                input_schema=payload.input_schema,
                output_schema=payload.output_schema,
                prerequisites=payload.prerequisites,
                required_capabilities=payload.required_capabilities,
                allowed_tool_names=payload.allowed_tool_names,
                procedure=[s.model_dump() for s in payload.procedure],
                verification_procedure=payload.verification_procedure.model_dump(),
                failure_modes=payload.failure_modes,
                rollback_strategy=payload.rollback_strategy or {},
                quality_requirements=payload.quality_requirements,
                security_constraints=payload.security_constraints,
                permission_requirements=payload.permission_requirements,
                risk_class=payload.risk_class,
                estimated_effort=payload.estimated_effort,
                expected_duration_seconds=payload.expected_duration_seconds,
                cost_estimate=payload.cost_estimate,
                reusable_components=payload.reusable_components,
                evidence_requirements=payload.evidence_requirements,
                metadata_json={
                    "solution_patterns": [sp.model_dump() for sp in payload.solution_patterns],
                    "knowledge_resources": [kr.model_dump() for kr in payload.knowledge_resources],
                    **payload.metadata,
                },
            )
            session.add(skill)

            audit = AuditEvent(
                actor=actor,
                action="skill.register",
                target_type="skill",
                target_id=f"{payload.skill_id}:{payload.version}",
                risk_level=ToolRiskLevel.LOW,
                result="SUCCESS",
                reason="Registered new draft skill version",
            )
            session.add(audit)
            
            try:
                await session.commit()
                await session.refresh(skill)
            except IntegrityError as ex:
                await session.rollback()
                raise SkillRegistryError(f"Database constraint violation: {ex}")

            logger.info(f"Skill '{skill.skill_id}' v{skill.version} registered as DRAFT")
            return skill

    async def validate_skill_payload(self, payload: SkillDefinitionPayload) -> Dict[str, Any]:
        """Comprehensive static & security checks on a skill payload."""
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Semver validity
        if not SEMVER_REGEX.match(payload.version):
            errors.append(f"Invalid semantic version: {payload.version}")

        # 2. Tool verification against registered tools in ToolGateway
        for tool_name in payload.allowed_tool_names:
            if tool_name not in tool_gateway._tools:
                errors.append(f"Tool '{tool_name}' is not registered in ToolGateway")

        # 3. Procedure verification
        if not payload.procedure:
            errors.append("Skill must declare at least one procedure step")
        step_ids = set()
        for step in payload.procedure:
            if step.step_id in step_ids:
                errors.append(f"Duplicate step_id '{step.step_id}' in procedure")
            step_ids.add(step.step_id)

            # Step tools must be a subset of skill's allowed_tool_names
            for st in step.allowed_tools:
                if st not in payload.allowed_tool_names:
                    errors.append(
                        f"Step '{step.step_id}' uses tool '{st}' not declared in allowed_tool_names"
                    )

        # 4. Secret detection: Ensure no hardcoded secrets or sensitive tokens
        payload_dump = payload.model_dump()
        redacted = redact_dict(payload_dump)
        if json_has_masked_secrets(redacted, payload_dump):
            errors.append("Skill definition contains embedded secrets or credentials")

        # 5. Schema checks
        if not isinstance(payload.input_schema, dict) or "type" not in payload.input_schema:
            errors.append("input_schema must be a valid JSONSchema object with 'type'")
        if not isinstance(payload.output_schema, dict) or "type" not in payload.output_schema:
            errors.append("output_schema must be a valid JSONSchema object with 'type'")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    async def publish_skill(self, skill_id: str, version: str, actor: str = "OPERATOR") -> SkillDefinition:
        """Transitions skill to PUBLISHED. Once published, it becomes strictly immutable."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == skill_id,
                SkillDefinition.version == version,
            )
            skill = (await session.execute(stmt)).scalar_one_or_none()
            if not skill:
                raise SkillNotFoundError(f"Skill '{skill_id}' v{version} not found")

            if skill.status == SkillStatus.PUBLISHED:
                return skill

            if skill.status not in (SkillStatus.DRAFT, SkillStatus.VALIDATING):
                raise SkillRegistryError(f"Cannot publish skill with status '{skill.status}'")

            # Final validation check before publication
            skill.status = SkillStatus.PUBLISHED
            skill.published_at = datetime.now(timezone.utc)

            # Initialize metrics row if not present
            metrics_stmt = select(SkillMetrics).where(
                SkillMetrics.skill_id == skill_id,
                SkillMetrics.version == version,
            )
            existing_metrics = (await session.execute(metrics_stmt)).scalar_one_or_none()
            if not existing_metrics:
                m = SkillMetrics(skill_id=skill_id, version=version)
                session.add(m)

            audit = AuditEvent(
                actor=actor,
                action="skill.publish",
                target_type="skill",
                target_id=f"{skill_id}:{version}",
                risk_level=ToolRiskLevel.MEDIUM,
                result="SUCCESS",
                reason=f"Published skill '{skill_id}' v{version}",
            )
            session.add(audit)
            await session.commit()
            await session.refresh(skill)
            logger.info(f"Skill '{skill_id}' v{version} successfully PUBLISHED")
            return skill

    async def deprecate_skill(self, skill_id: str, version: str, actor: str = "OPERATOR") -> SkillDefinition:
        """Marks a skill as DEPRECATED. Existing runs complete; new runs cannot resolve it."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == skill_id,
                SkillDefinition.version == version,
            )
            skill = (await session.execute(stmt)).scalar_one_or_none()
            if not skill:
                raise SkillNotFoundError(f"Skill '{skill_id}' v{version} not found")

            skill.status = SkillStatus.DEPRECATED
            skill.deprecated_at = datetime.now(timezone.utc)

            audit = AuditEvent(
                actor=actor,
                action="skill.deprecate",
                target_type="skill",
                target_id=f"{skill_id}:{version}",
                risk_level=ToolRiskLevel.MEDIUM,
                result="SUCCESS",
                reason=f"Deprecated skill '{skill_id}' v{version}",
            )
            session.add(audit)
            await session.commit()
            await session.refresh(skill)
            return skill

    async def disable_skill(self, skill_id: str, version: str, actor: str = "OPERATOR") -> SkillDefinition:
        """Disables a skill immediately. Rejects all executions."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == skill_id,
                SkillDefinition.version == version,
            )
            skill = (await session.execute(stmt)).scalar_one_or_none()
            if not skill:
                raise SkillNotFoundError(f"Skill '{skill_id}' v{version} not found")

            skill.status = SkillStatus.DISABLED

            audit = AuditEvent(
                actor=actor,
                action="skill.disable",
                target_type="skill",
                target_id=f"{skill_id}:{version}",
                risk_level=ToolRiskLevel.HIGH,
                result="SUCCESS",
                reason=f"Disabled skill '{skill_id}' v{version}",
            )
            session.add(audit)
            await session.commit()
            await session.refresh(skill)
            return skill

    async def get_skill_version(self, skill_id: str, version: str) -> Optional[SkillDefinition]:
        """Fetch exact skill version."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == skill_id,
                SkillDefinition.version == version,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def resolve_compatible_skill(
        self,
        skill_id: str,
        requested_version: Optional[str] = None,
        allow_historical_replay: bool = False,
    ) -> SkillDefinition:
        """Deterministically resolves the exact version to execute."""
        async with async_session_factory() as session:
            if requested_version:
                stmt = select(SkillDefinition).where(
                    SkillDefinition.skill_id == skill_id,
                    SkillDefinition.version == requested_version,
                )
                skill = (await session.execute(stmt)).scalar_one_or_none()
                if not skill:
                    raise SkillNotFoundError(f"Skill '{skill_id}' version '{requested_version}' not found")
                
                if skill.status == SkillStatus.DISABLED:
                    raise SkillRegistryError(f"Skill '{skill_id}' v{requested_version} is DISABLED and cannot be executed")
                if skill.status == SkillStatus.DEPRECATED and not allow_historical_replay:
                    raise SkillRegistryError(f"Skill '{skill_id}' v{requested_version} is DEPRECATED and not permitted for new runs")
                if skill.status != SkillStatus.PUBLISHED and not allow_historical_replay:
                    raise SkillRegistryError(f"Skill '{skill_id}' v{requested_version} is not PUBLISHED (status: {skill.status})")
                return skill

            # If version is omitted, find highest PUBLISHED semver
            stmt = select(SkillDefinition).where(
                SkillDefinition.skill_id == skill_id,
                SkillDefinition.status == SkillStatus.PUBLISHED,
            )
            skills = (await session.execute(stmt)).scalars().all()
            if not skills:
                raise SkillNotFoundError(f"No active PUBLISHED versions found for skill '{skill_id}'")

            # Sort descending by semver tuple
            sorted_skills = sorted(
                skills,
                key=lambda s: parse_semver(s.version),
                reverse=True,
            )
            return sorted_skills[0]

    async def list_skills(
        self,
        category: Optional[str] = None,
        status: Optional[SkillStatus] = None,
    ) -> List[SkillDefinition]:
        """List skills with optional filtering."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition)
            if category:
                stmt = stmt.where(SkillDefinition.category == category)
            if status:
                stmt = stmt.where(SkillDefinition.status == status)
            stmt = stmt.order_by(SkillDefinition.skill_id, desc(SkillDefinition.version))
            return list((await session.execute(stmt)).scalars().all())

    async def list_skill_versions(self, skill_id: str) -> List[SkillDefinition]:
        """List all versions of a specific skill ordered by semver descending."""
        async with async_session_factory() as session:
            stmt = select(SkillDefinition).where(SkillDefinition.skill_id == skill_id)
            skills = list((await session.execute(stmt)).scalars().all())
            return sorted(skills, key=lambda s: parse_semver(s.version), reverse=True)


def json_has_masked_secrets(redacted: Any, original: Any) -> bool:
    """Checks if secret redactor replaced any sensitive string with [REDACTED...]."""
    if isinstance(redacted, dict) and isinstance(original, dict):
        for k, v in redacted.items():
            orig_v = original.get(k)
            if isinstance(v, str) and "[REDACTED" in v:
                return True
            if json_has_masked_secrets(v, orig_v):
                return True
    elif isinstance(redacted, list) and isinstance(original, list):
        for r_item, o_item in zip(redacted, original):
            if json_has_masked_secrets(r_item, o_item):
                return True
    return False


skill_registry = SkillRegistry()
