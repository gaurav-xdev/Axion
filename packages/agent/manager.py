"""Autonomous Business Decision Manager.
The central decision-making system driving continuous commercial operations:

Control Loop:
  OBSERVE -> STATE -> GOAL -> PLAN -> ACT -> OBSERVE RESULT -> VERIFY -> UPDATE STATE -> REPLAN

Continuously answers:
- What is happening in the business pipeline?
- What opportunities exist and what is their economic value?
- What should happen next and why?
- Which specialized logical agent and skill should execute it?
- What are the risks and required permissions?
- What happens if it fails?
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from packages.agent.capabilities import AgentCapabilityProfile, AgentDomain, agent_registry
from packages.agent.dispatcher import DispatchTaskMessage, task_dispatcher
from packages.memory.context import memory_manager
from packages.observability.logger import logger
from packages.projects.economic_model import economic_evaluator
from packages.projects.revenue import FunnelBottleneckDiagnosis, FunnelMetrics, revenue_optimization_engine
from packages.security.emergency import emergency_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import (
    AuditEvent,
    Contact,
    Message,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    ProjectTask,
    Prospect,
    TaskStatus,
    ToolRiskLevel,
    utc_now,
)


class BusinessStateObservation(BaseModel):
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trailing_7d_revenue_usd: float = 0.0
    target_weekly_revenue_usd: float = 1200.0
    weekly_pacing_percentage: float = 0.0
    revenue_gap_usd: float = 0.0
    funnel_metrics: Dict[str, Any] = Field(default_factory=dict)
    primary_bottleneck: str = "NONE"
    bottleneck_severity: str = "HEALTHY"
    strategic_recommendations: List[str] = Field(default_factory=list)
    top_priority_prospects_count: int = 0
    pending_inbounds_count: int = 0
    paid_projects_awaiting_execution: int = 0
    executing_projects_count: int = 0
    failed_tasks_count: int = 0
    emergency_stopped: bool = False
    emergency_paused: bool = False


class ManagerDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str
    target_entity_id: Optional[str] = None
    target_agent_id: str
    target_skill_id: Optional[str] = None
    expected_value_usd: float = 0.0
    risk_assessment: str = "LOW"
    required_permissions: List[str] = Field(default_factory=list)
    decision_rationale: str
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)
    contingency_on_failure: str
    success_verification_criteria: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AutonomousBusinessManager:
    """Central decision-making system governing the autonomous business."""

    async def observe_current_state(self) -> BusinessStateObservation:
        """Collects authoritative metrics across revenue, funnel, prospects, and projects."""
        emergency = await emergency_service.get_state()
        funnel_intel = await revenue_optimization_engine.get_revenue_intelligence(window_days=30)
        metrics = funnel_intel["metrics"]
        bottleneck = funnel_intel["bottleneck_diagnosis"]

        async with async_session_factory() as session:
            # 1. Unhandled inbounds
            inbound_stmt = select(func.count(Message.id)).where(
                Message.direction == "INBOUND",
                Message.created_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            )
            pending_inbounds = int((await session.execute(inbound_stmt)).scalar() or 0)

            # 2. Paid projects awaiting plan / execution
            paid_stmt = select(func.count(Project.id)).where(Project.status == ProjectStatus.PAID)
            paid_count = int((await session.execute(paid_stmt)).scalar() or 0)

            # 3. Executing projects
            exec_stmt = select(func.count(Project.id)).where(Project.status == ProjectStatus.EXECUTING)
            exec_count = int((await session.execute(exec_stmt)).scalar() or 0)

            # 4. Failed tasks needing diagnosis / replanning
            fail_stmt = select(func.count(ProjectTask.id)).where(ProjectTask.status == TaskStatus.FAILED)
            failed_count = int((await session.execute(fail_stmt)).scalar() or 0)

            # 5. Top qualified prospects
            prospect_stmt = (
                select(func.count(Prospect.id))
                .where(Prospect.status == "QUALIFIED")
                .where(Prospect.last_contacted_at.is_(None))
            )
            top_prospects = int((await session.execute(prospect_stmt)).scalar() or 0)

        revenue_7d = metrics["trailing_7d_revenue_usd"]
        gap = max(0.0, round(1200.0 - revenue_7d, 2))
        pacing = round((revenue_7d / 1200.0) * 100, 1)

        return BusinessStateObservation(
            trailing_7d_revenue_usd=revenue_7d,
            target_weekly_revenue_usd=1200.0,
            weekly_pacing_percentage=pacing,
            revenue_gap_usd=gap,
            funnel_metrics=metrics,
            primary_bottleneck=bottleneck["primary_bottleneck"],
            bottleneck_severity=bottleneck["severity"],
            strategic_recommendations=bottleneck["actionable_recommendations"],
            top_priority_prospects_count=top_prospects,
            pending_inbounds_count=pending_inbounds,
            paid_projects_awaiting_execution=paid_count,
            executing_projects_count=exec_count,
            failed_tasks_count=failed_count,
            emergency_stopped=emergency.is_stopped,
            emergency_paused=emergency.is_paused,
        )

    async def evaluate_and_decide(self, obs: BusinessStateObservation) -> List[ManagerDecision]:
        """Evaluates observed business state and produces priority-ordered, evidence-backed decisions."""
        decisions: List[ManagerDecision] = []

        # 1. Authoritative Emergency Check
        if obs.emergency_stopped:
            agent = agent_registry.get_agent("software_architect_agent")
            decisions.append(
                ManagerDecision(
                    action_type="EMERGENCY_HALT",
                    target_agent_id=agent.agent_id if agent else "system",
                    decision_rationale="Emergency STOP is ACTIVE. Halting all commercial side-effects.",
                    contingency_on_failure="Maintain sleep state until operator clears stop flag.",
                    success_verification_criteria="Zero external side-effects dispatched.",
                )
            )
            return decisions

        # 2. Priority 1: Handle Failed Tasks via Replanning
        if obs.failed_tasks_count > 0:
            async with async_session_factory() as session:
                failed_stmt = (
                    select(ProjectTask)
                    .join(Project, ProjectTask.project_id == Project.id)
                    .where(ProjectTask.status == TaskStatus.FAILED)
                    .order_by(ProjectTask.created_at.desc())
                    .limit(5)
                )
                failed_tasks = (await session.execute(failed_stmt)).scalars().all()
                for ft in failed_tasks:
                    agent = agent_registry.resolve_agent_for_task(ft.worker_type, preferred_domain=AgentDomain.ENGINEERING)
                    decisions.append(
                        ManagerDecision(
                            action_type="REPLAN_FAILED_TASK",
                            target_entity_id=ft.project_id,
                            target_agent_id=agent.agent_id,
                            target_skill_id=ft.input_payload.get("skill_id") if ft.input_payload else None,
                            expected_value_usd=1000.0,
                            risk_assessment="MEDIUM",
                            required_permissions=["tools:execute"],
                            decision_rationale=f"Diagnose and remediate failed milestone task '{ft.description}' for project {ft.project_id}.",
                            evidence_summary={"failed_task_id": ft.id, "failure_evidence": ft.evidence},
                            contingency_on_failure="Escalate to operator review if 2 consecutive replans fail.",
                            success_verification_criteria="Corrective task enqueued and passes verification.",
                        )
                    )

        # 3. Priority 2: Plan and Execute Paid Projects
        if obs.paid_projects_awaiting_execution > 0:
            async with async_session_factory() as session:
                paid_stmt = select(Project).where(Project.status == ProjectStatus.PAID).limit(5)
                paid_projs = (await session.execute(paid_stmt)).scalars().all()
                for pp in paid_projs:
                    agent = agent_registry.get_agent("software_architect_agent") or agent_registry.resolve_agent_for_task("plan_project")
                    decisions.append(
                        ManagerDecision(
                            action_type="PLAN_PAID_PROJECT",
                            target_entity_id=pp.id,
                            target_agent_id=agent.agent_id,
                            expected_value_usd=float(pp.accepted_price),
                            risk_assessment="LOW",
                            required_permissions=["tools:execute"],
                            decision_rationale=f"Funded project '{pp.name}' ($ {pp.accepted_price:,.2f}) requires multi-skill milestone planning and execution.",
                            evidence_summary={"project_id": pp.id, "accepted_price": pp.accepted_price},
                            contingency_on_failure="Replan with alternative skill configuration.",
                            success_verification_criteria="Milestone tasks created and advanced to EXECUTING.",
                        )
                    )

        # 4. Priority 3: Dispatch Outreach for High-EV Qualified Prospects
        if obs.top_priority_prospects_count > 0 and not obs.emergency_paused:
            async with async_session_factory() as session:
                prosp_stmt = (
                    select(Prospect)
                    .where(Prospect.status == "QUALIFIED")
                    .where(Prospect.last_contacted_at.is_(None))
                    .order_by(Prospect.qualification_score.desc())
                    .limit(3)
                )
                top_prosp = (await session.execute(prosp_stmt)).scalars().all()
                for pr in top_prosp:
                    agent = agent_registry.get_agent("outreach_agent") or agent_registry.resolve_agent_for_task("outreach")
                    decisions.append(
                        ManagerDecision(
                            action_type="DISPATCH_OUTREACH",
                            target_entity_id=pr.id,
                            target_agent_id=agent.agent_id,
                            expected_value_usd=pr.qualification_score * 750.0,
                            risk_assessment="LOW",
                            required_permissions=["tools:execute", "communications:dispatch"],
                            decision_rationale=f"Qualified prospect '{pr.business_name}' (Score: {pr.qualification_score}) ready for compliant value outreach.",
                            evidence_summary={"prospect_id": pr.id, "domain": pr.domain, "score": pr.qualification_score},
                            contingency_on_failure="Mark contact retry with exponential backoff.",
                            success_verification_criteria="Outreach message dispatched with anti-spam compliance.",
                        )
                    )

        # 5. Default Strategic Decision if pipeline is idle
        if not decisions:
            agent = agent_registry.get_agent("revenue_agent") or agent_registry.resolve_agent_for_task("record_project_outcome")
            decisions.append(
                ManagerDecision(
                    action_type="MAINTAIN_OPERATIONAL_CADENCE",
                    target_agent_id=agent.agent_id,
                    expected_value_usd=0.0,
                    risk_assessment="READ_ONLY",
                    required_permissions=[],
                    decision_rationale=f"Pipeline is balanced. 7d Revenue: ${obs.trailing_7d_revenue_usd:,.2f} ({obs.weekly_pacing_percentage}% of target). Maintain discovery scanning.",
                    evidence_summary={"pacing_pct": obs.weekly_pacing_percentage, "gap_usd": obs.revenue_gap_usd},
                    contingency_on_failure="Sleep until next observation interval.",
                    success_verification_criteria="Observation logged and metrics tracked.",
                )
            )

        return decisions

    async def execute_decision(self, decision: ManagerDecision) -> Dict[str, Any]:
        """Dispatches concrete actions via specialized agents, skills, and tools."""
        logger.info(f"Manager executing decision {decision.decision_id}: {decision.action_type} via {decision.target_agent_id}")

        # Record in Episodic Memory
        memory_manager.record_episodic_event(
            event_type=f"MANAGER_DECISION_{decision.action_type}",
            entity_id=decision.target_entity_id or "system",
            description=decision.decision_rationale,
            evidence={
                "target_agent": decision.target_agent_id,
                "expected_value_usd": decision.expected_value_usd,
                "risk_assessment": decision.risk_assessment,
            },
        )

        # Persist Audit Event
        async with async_session_factory() as session:
            audit = AuditEvent(
                actor=decision.target_agent_id,
                action=f"decision.{decision.action_type.lower()}",
                target_type="project" if decision.target_entity_id else "system",
                target_id=decision.target_entity_id or "global",
                risk_level=ToolRiskLevel.LOW if decision.risk_assessment == "LOW" else ToolRiskLevel.MEDIUM,
                result="EXECUTING",
                reason=decision.decision_rationale,
            )
            session.add(audit)
            await session.commit()

        try:
            if decision.action_type == "PLAN_PAID_PROJECT" and decision.target_entity_id:
                from packages.projects.manager import project_planning_engine
                tasks = await project_planning_engine.plan_project(decision.target_entity_id)
                return {"status": "PLANNED", "tasks_count": len(tasks)}

            elif decision.action_type == "REPLAN_FAILED_TASK" and decision.target_entity_id:
                from packages.projects.manager import project_planning_engine
                tasks = await project_planning_engine.replan_project(
                    project_id=decision.target_entity_id,
                    failed_task_id=decision.evidence_summary.get("failed_task_id", ""),
                    failure_reason=str(decision.evidence_summary.get("failure_evidence", "Task execution error")),
                )
                return {"status": "REPLANNED", "tasks_count": len(tasks)}

            elif decision.action_type == "DISPATCH_OUTREACH" and decision.target_entity_id:
                async with async_session_factory() as session:
                    pr = await session.get(Prospect, decision.target_entity_id)
                    contact_stmt = select(Contact).where(Contact.prospect_id == decision.target_entity_id)
                    contact = (await session.execute(contact_stmt)).scalars().first()
                    if pr and contact and contact.email and not contact.opt_out and not pr.opt_out:
                        # Build evidence-derived personalized outreach
                        pain_summary = []
                        if isinstance(pr.pain_points, dict):
                            pts = pr.pain_points.get("points", [])
                            obs_list = pr.pain_points.get("observations", [])
                            if pts:
                                pain_summary.extend(pts)
                            for ob in obs_list:
                                if isinstance(ob, dict) and ob.get("statement"):
                                    pain_summary.append(ob["statement"])
                                elif hasattr(ob, "statement"):
                                    pain_summary.append(ob.statement)

                        target_name = contact.name or pr.business_name
                        if pain_summary:
                            evidence_focus = f"Specifically, we observed integration requirements regarding: {pain_summary[0]}."
                        else:
                            evidence_focus = f"We analyzed the {pr.industry or 'operational'} workflow infrastructure for {pr.business_name}."

                        personalized_content = (
                            f"Hello {target_name},\n\n"
                            f"{evidence_focus}\n\n"
                            f"We engineer and deploy fixed-price autonomous backend workflows and API integrations, "
                            f"backed by 5-layer adversarial QA and delivered with full cryptographic test manifests.\n\n"
                            f"Would you be open to reviewing a scope and fixed quote for {pr.business_name}?\n\n"
                            f"Best regards,\nAxion Autonomous Engineering"
                        )

                        from packages.tools.base import ToolRequest
                        from packages.tools.gateway import tool_gateway

                        tool_req = ToolRequest(
                            tool_name="communication.dispatch",
                            arguments={
                                "recipient": contact.email,
                                "sender": settings.SMTP_FROM_EMAIL,
                                "subject": f"Technical workflow integration: {pr.business_name}",
                                "content": personalized_content,
                                "channel": "EMAIL",
                                "prospect_id": pr.id,
                            },
                            requested_by_role="OPERATOR",
                            client_id=pr.id,
                            idempotency_key=f"mgr_outreach_{pr.id}_{int(datetime.now(timezone.utc).timestamp())}",
                        )
                        tool_res = await tool_gateway.execute(tool_req)
                        if tool_res.success:
                            pr.status = "CONTACTED"
                            pr.last_contacted_at = datetime.now(timezone.utc)
                            await session.commit()
                            return {"status": "OUTREACH_SENT", "message_id": tool_res.data.get("message_id")}
                        else:
                            return {"status": "OUTREACH_FAILED", "error": tool_res.error}

            return {"status": "ACKNOWLEDGED", "action": decision.action_type}
        except Exception as e:
            logger.error(f"Error executing decision {decision.decision_id} ({decision.action_type}): {e}", exc_info=True)
            return {"status": "FAILED", "error": str(e), "action": decision.action_type}

    async def run_control_cycle(self) -> Dict[str, Any]:
        """Executes one complete state-driven control cycle."""
        logger.info("[Control Cycle] Initiating autonomous business observation...")
        obs = await self.observe_current_state()

        logger.info(
            f"[Control Cycle] Observed: 7d Revenue=${obs.trailing_7d_revenue_usd:,.2f} "
            f"({obs.weekly_pacing_percentage}% pacing), Bottleneck={obs.primary_bottleneck}, "
            f"PaidProjects={obs.paid_projects_awaiting_execution}, FailedTasks={obs.failed_tasks_count}"
        )

        decisions = await self.evaluate_and_decide(obs)
        executed_results = []
        for dec in decisions:
            res = await self.execute_decision(dec)
            executed_results.append({"decision_id": dec.decision_id, "action": dec.action_type, "result": res})

        return {
            "observation": obs.model_dump(),
            "decisions_count": len(decisions),
            "executed_results": executed_results,
            "cycle_completed_at": datetime.now(timezone.utc).isoformat(),
        }


# Authoritative singleton
autonomous_business_manager = AutonomousBusinessManager()
