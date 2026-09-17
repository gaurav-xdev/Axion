"""Pydantic schemas and contract definitions for the Skill Registry & Execution Engine.
Enforces strict machine-readable contracts, validation rules, and future compatibility interfaces.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from packages.shared.models import (
    FailureClassification,
    SkillActionType,
    SkillExecutionStatus,
    SkillStatus,
    ToolRiskLevel,
)

SEMVER_REGEX = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$")
SKILL_ID_REGEX = re.compile(r"^[a-z0-9_]+$")


class SolutionPatternRef(BaseModel):
    """Compatibility interface for future Proven Solution Library integration."""
    solution_id: str
    version: str = "1.0.0"
    adaptation_rules: Dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = 1.0


class KnowledgeResourceRef(BaseModel):
    """Compatibility interface for future Knowledge Resource Pack integration."""
    resource_id: str
    source_uri: str
    license_or_provenance: str
    version: str = "1.0.0"
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trust_level: str = "VERIFIED_INTERNAL"


class ProcedureStep(BaseModel):
    """Structured step within a deterministic Skill Procedure."""
    step_id: str
    description: str
    objective: str
    action_type: SkillActionType
    required_inputs: List[str] = Field(default_factory=list)
    expected_output: str
    allowed_tools: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    retry_policy: Dict[str, Any] = Field(default_factory=lambda: {"max_retries": 2, "backoff": "exponential"})
    verification: Dict[str, Any] = Field(default_factory=dict)
    evidence_required: List[str] = Field(default_factory=list)
    failure_policy: str = Field(default="FAIL_IMMEDIATELY")  # FAIL_IMMEDIATELY, RETRY, SKIP, ROLLBACK


class VerificationCheck(BaseModel):
    check_name: str
    check_type: str  # SCHEMA, TOOL_OUTPUT, ARTIFACT_EXISTS, CODE_ANALYSIS, EXTERNAL_PROBE
    description: str
    expected_criteria: Dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class VerificationProcedure(BaseModel):
    """Rigorous verification criteria that must pass for a skill execution to succeed."""
    checks: List[VerificationCheck] = Field(default_factory=list)
    required_evidence_keys: List[str] = Field(default_factory=list)
    score_threshold: float = Field(default=1.0, ge=0.0, le=1.0)


class SkillDefinitionPayload(BaseModel):
    """Payload for registering or validating a skill definition."""
    skill_id: str
    name: str
    description: str
    category: str
    purpose: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    prerequisites: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    allowed_tool_names: List[str] = Field(default_factory=list)
    procedure: List[ProcedureStep]
    verification_procedure: VerificationProcedure
    failure_modes: List[Dict[str, Any]] = Field(default_factory=list)
    rollback_strategy: Optional[Dict[str, Any]] = Field(default_factory=dict)
    quality_requirements: List[str] = Field(default_factory=list)
    security_constraints: List[str] = Field(default_factory=list)
    permission_requirements: List[str] = Field(default_factory=list)
    risk_class: ToolRiskLevel = ToolRiskLevel.LOW
    estimated_effort: float = 1.0
    expected_duration_seconds: int = 60
    cost_estimate: float = 0.0
    reusable_components: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_requirements: List[str] = Field(default_factory=list)
    solution_patterns: List[SolutionPatternRef] = Field(default_factory=list)
    knowledge_resources: List[KnowledgeResourceRef] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, v: str) -> str:
        if not SKILL_ID_REGEX.match(v):
            raise ValueError(f"skill_id '{v}' must be alphanumeric lowercase with underscores only.")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not SEMVER_REGEX.match(v):
            raise ValueError(f"version '{v}' must strictly follow Semantic Versioning (MAJOR.MINOR.PATCH).")
        return v


class SkillExecutionRequest(BaseModel):
    """Request to initiate a skill execution."""
    skill_id: str
    version: Optional[str] = None  # If omitted, resolves highest compatible PUBLISHED version
    input_data: Dict[str, Any]
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_run_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    max_steps: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=5, le=3600)
    max_cost: float = Field(default=5.0, ge=0.0)


class SkillExecutionResult(BaseModel):
    """Final outcome of a Skill Execution."""
    execution_id: str
    skill_id: str
    version: str
    status: SkillExecutionStatus
    current_step: int
    output: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    failure_class: Optional[FailureClassification] = None
    duration_ms: int = 0
    cost: float = 0.0
    metrics: Dict[str, Any] = Field(default_factory=dict)
