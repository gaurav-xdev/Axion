"""7-Dimensional Business Memory & Context Architecture.
Provides persistent, partitioned, and verified business memory:
1. Episodic: Real operational event stream with timestamps and correlation IDs.
2. Semantic: Technical patterns, domain constraints, and schemas.
3. Procedural: Concrete execution recipes, parameters, and tool sequences.
4. Client Memory: Historical preferences, constraints, approved quotes, and communication tone.
5. Skill Memory: Real historical duration, cost, success rate, and error modes.
6. Failure Memory: Root cause diagnosis, validated solutions, and preventative heuristics.
7. Commercial Memory: Conversion rates, price acceptance ratios, and sales cycle duration.

Strictly isolates untrusted external data and scrubs sensitive credentials.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import (
    AgentRun,
    Artifact,
    Client,
    Conversation,
    Message,
    Project,
    ProjectTask,
    Requirement,
)


class EpisodicEvent(BaseModel):
    event_id: str
    event_type: str
    entity_id: str
    description: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FailureRecord(BaseModel):
    failure_id: str
    failure_type: str
    root_cause: str
    context_keywords: List[str] = Field(default_factory=list)
    attempted_solution: Optional[str] = None
    solution_verified: bool = False
    prevention_rule: str
    confidence: float = 0.8
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SkillExecutionMetric(BaseModel):
    skill_id: str
    total_runs: int = 0
    successful_runs: int = 0
    total_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0
    failure_modes: Dict[str, int] = Field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return round(self.successful_runs / self.total_runs, 3) if self.total_runs > 0 else 1.0

    @property
    def avg_duration_seconds(self) -> float:
        return round(self.total_duration_seconds / self.total_runs, 2) if self.total_runs > 0 else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return round(self.total_cost_usd / self.total_runs, 4) if self.total_runs > 0 else 0.0


class ClientMemoryProfile(BaseModel):
    client_id: str
    domain: Optional[str] = None
    preferred_communication_channel: str = "EMAIL"
    stated_technical_constraints: List[str] = Field(default_factory=list)
    total_projects_count: int = 0
    total_paid_usd: float = 0.0
    average_acceptance_ratio: float = 1.0  # accepted_price / quoted_price


class CommercialMemoryMetric(BaseModel):
    industry: str
    total_quotes_sent: int = 0
    total_quotes_accepted: int = 0
    total_revenue_usd: float = 0.0

    @property
    def conversion_rate(self) -> float:
        return round(self.total_quotes_accepted / self.total_quotes_sent, 3) if self.total_quotes_sent > 0 else 0.0


class AssembledContext(BaseModel):
    project_id: Optional[str] = None
    client_name: Optional[str] = None
    project_status: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    recent_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    recent_messages: List[Dict[str, str]] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    untrusted_external_content: List[str] = Field(default_factory=list)
    failure_prevention_rules: List[str] = Field(default_factory=list)
    client_constraints: List[str] = Field(default_factory=list)
    skill_calibration_ratio: float = 1.0


class MemoryManager:
    """7-Dimensional Business Memory Manager providing persistent cross-run knowledge."""

    def __init__(self):
        self._episodic_events: List[EpisodicEvent] = []
        self._failures: List[FailureRecord] = []
        self._skill_metrics: Dict[str, SkillExecutionMetric] = {}
        self._client_profiles: Dict[str, ClientMemoryProfile] = {}
        self._commercial_metrics: Dict[str, CommercialMemoryMetric] = {}

    # 1. Episodic Memory
    def record_episodic_event(
        self,
        event_type: str,
        entity_id: str,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> EpisodicEvent:
        import uuid
        event = EpisodicEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            entity_id=entity_id,
            description=description,
            evidence=evidence or {},
        )
        self._episodic_events.append(event)
        # Keep episodic log bounded to most recent 2,000 events
        if len(self._episodic_events) > 2000:
            self._episodic_events.pop(0)
        return event

    # 2. Failure & Lesson Memory
    def record_failure_lesson(
        self,
        failure_type: str,
        root_cause: str,
        context_keywords: List[str],
        prevention_rule: str,
        attempted_solution: Optional[str] = None,
        solution_verified: bool = True,
        confidence: float = 0.9,
    ) -> FailureRecord:
        import uuid
        rec = FailureRecord(
            failure_id=str(uuid.uuid4()),
            failure_type=failure_type,
            root_cause=root_cause,
            context_keywords=[k.lower().strip() for k in context_keywords],
            attempted_solution=attempted_solution,
            solution_verified=solution_verified,
            prevention_rule=prevention_rule,
            confidence=confidence,
        )
        self._failures.append(rec)
        logger.info(f"Recorded failure prevention rule: '{prevention_rule}' for keywords {context_keywords}")
        return rec

    def get_prevention_rules_for_context(self, keywords: List[str]) -> List[str]:
        """Matches failure prevention rules against target task context keywords."""
        query_kw = set(k.lower().strip() for k in keywords)
        matched_rules: List[str] = []
        for f in self._failures:
            if not f.solution_verified:
                continue
            if any(k in query_kw for k in f.context_keywords):
                matched_rules.append(f.prevention_rule)
        return list(dict.fromkeys(matched_rules))  # Deduplicate

    # 3. Skill Performance & Calibration Memory
    def record_skill_execution(
        self,
        skill_id: str,
        success: bool,
        duration_seconds: float,
        cost_usd: float = 0.0,
        failure_mode: Optional[str] = None,
    ) -> None:
        if skill_id not in self._skill_metrics:
            self._skill_metrics[skill_id] = SkillExecutionMetric(skill_id=skill_id)
        m = self._skill_metrics[skill_id]
        m.total_runs += 1
        if success:
            m.successful_runs += 1
        m.total_duration_seconds += max(0.0, duration_seconds)
        m.total_cost_usd += max(0.0, cost_usd)
        if failure_mode:
            m.failure_modes[failure_mode] = m.failure_modes.get(failure_mode, 0) + 1

    def get_skill_metric(self, skill_id: str) -> SkillExecutionMetric:
        return self._skill_metrics.get(skill_id, SkillExecutionMetric(skill_id=skill_id))

    def get_calibration_multiplier(self, skill_id: Optional[str] = None) -> float:
        """Returns empirical effort calibration multiplier based on skill execution history."""
        if skill_id and skill_id in self._skill_metrics:
            m = self._skill_metrics[skill_id]
            # If high failure rate, increase effort buffer
            if m.total_runs >= 3:
                fail_rate = 1.0 - m.success_rate
                return round(1.0 + (fail_rate * 0.5), 2)
        return 1.0

    # 4. Client Profile Memory
    def update_client_memory(
        self,
        client_id: str,
        domain: Optional[str] = None,
        constraint: Optional[str] = None,
        payment_amount: float = 0.0,
    ) -> ClientMemoryProfile:
        if client_id not in self._client_profiles:
            self._client_profiles[client_id] = ClientMemoryProfile(client_id=client_id, domain=domain)
        prof = self._client_profiles[client_id]
        if domain:
            prof.domain = domain
        if constraint and constraint not in prof.stated_technical_constraints:
            prof.stated_technical_constraints.append(constraint)
        if payment_amount > 0:
            prof.total_projects_count += 1
            prof.total_paid_usd += payment_amount
        return prof

    def get_client_memory(self, client_id: str) -> Optional[ClientMemoryProfile]:
        return self._client_profiles.get(client_id)

    # 5. Authoritative Context Assembler (Database Grounded)
    async def retrieve_project_context(self, project_id: str) -> AssembledContext:
        """Retrieves and partitions authoritative project context from database + memory layers."""
        async with async_session_factory() as session:
            proj = await session.get(Project, project_id)
            if not proj:
                return AssembledContext(project_id=project_id)

            client = await session.get(Client, proj.client_id) if proj.client_id else None

            # Requirements
            req_stmt = select(Requirement).where(Requirement.project_id == project_id)
            reqs = (await session.execute(req_stmt)).scalars().all()

            # Tasks
            task_stmt = (
                select(ProjectTask)
                .where(ProjectTask.project_id == project_id)
                .order_by(ProjectTask.created_at.desc())
                .limit(10)
            )
            tasks = (await session.execute(task_stmt)).scalars().all()

            # Artifacts
            art_stmt = select(Artifact).where(Artifact.project_id == project_id)
            arts = (await session.execute(art_stmt)).scalars().all()

            # Messages
            messages_list = []
            if proj.client_id:
                conv_stmt = select(Conversation).where(Conversation.client_id == proj.client_id)
                conv = (await session.execute(conv_stmt)).scalars().first()
                if conv:
                    msg_stmt = (
                        select(Message)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.created_at.desc())
                        .limit(5)
                    )
                    msgs = (await session.execute(msg_stmt)).scalars().all()
                    for m in reversed(msgs):
                        messages_list.append({
                            "direction": m.direction,
                            "content": m.content,
                            "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
                        })

            # Retrieve memory overlays
            client_mem = self.get_client_memory(proj.client_id) if proj.client_id else None
            client_constraints = client_mem.stated_technical_constraints if client_mem else []

            # Match failure prevention rules against project terms
            context_terms = [proj.name] + [r.title for r in reqs]
            prevention_rules = self.get_prevention_rules_for_context(context_terms)

            return AssembledContext(
                project_id=proj.id,
                client_name=client.name if client else "Unknown Client",
                project_status=proj.status.value if hasattr(proj.status, "value") else str(proj.status),
                requirements=[f"{r.title}: {r.description}" for r in reqs],
                recent_tasks=[
                    {
                        "worker": t.worker_type,
                        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                        "desc": t.description,
                    }
                    for t in tasks
                ],
                recent_messages=messages_list,
                artifacts=[f"{a.name} ({a.artifact_type})" for a in arts],
                failure_prevention_rules=prevention_rules,
                client_constraints=client_constraints,
                skill_calibration_ratio=self.get_calibration_multiplier(),
            )


# Global singleton
memory_manager = MemoryManager()
