"""Autonomous Business Scheduler Service.
Operates 24/7 as the continuous commercial operator:
- Monitors weekly gross revenue against TARGET_REVENUE_USD_PER_WEEK = 1200.0
- Observes authoritative distributed emergency STOP / PAUSE controls
- Scans pipeline: Prospecting -> Outreach -> Scoping -> Payment -> Skill Execution -> QA -> Delivery
- Enqueues durable tasks to Redis Streams via DurableTaskDispatcher
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
import signal
import socket
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select

from packages.agent.dispatcher import task_dispatcher
from packages.agent.manager import autonomous_business_manager
from packages.observability.logger import logger
from packages.observability.metrics import AGENT_RUNS_TOTAL
from packages.security.emergency import emergency_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory, close_db, init_db
from packages.shared.models import (
    Client,
    Contact,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    ProjectTask,
    Prospect,
    Requirement,
    TaskStatus,
)

TARGET_REVENUE_USD_PER_WEEK = 1200.0
SCHEDULER_INTERVAL_SECONDS = 15.0

running = True
scheduler_id = f"scheduler_{socket.gethostname()}_{os.getpid()}"


def handle_exit(*args):
    global running
    logger.info(f"Scheduler {scheduler_id} received shutdown signal. Exiting gracefully...")
    running = False


class AutonomousSchedulerService:
    """24/7 background orchestrator driving the autonomous business pipeline."""

    def __init__(self):
        self.target_weekly_revenue = TARGET_REVENUE_USD_PER_WEEK

    async def calculate_weekly_revenue(self) -> Dict[str, Any]:
        """Calculates total gross revenue collected in the trailing 7 days."""
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        async with async_session_factory() as session:
            stmt = (
                select(func.coalesce(func.sum(Payment.amount), 0.0))
                .where(Payment.created_at >= week_ago)
                .where(Payment.status == PaymentStatus.PAID)
            )
            revenue_7d = float((await session.execute(stmt)).scalar() or 0.0)

        pacing_pct = round((revenue_7d / self.target_weekly_revenue) * 100, 1)
        remaining_gap = max(0.0, round(self.target_weekly_revenue - revenue_7d, 2))

        return {
            "target_weekly_revenue": self.target_weekly_revenue,
            "revenue_7d": revenue_7d,
            "pacing_percentage": pacing_pct,
            "remaining_gap": remaining_gap,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def check_pipeline_and_dispatch(self) -> Dict[str, int]:
        """Inspects business database state and dispatches pending commercial/technical work."""
        dispatched_counts = {
            "prospecting": 0,
            "outreach": 0,
            "execution": 0,
            "qa": 0,
        }

        # 1. Authoritative Emergency Check
        emergency = await emergency_service.get_state()
        if emergency.is_stopped:
            logger.info(f"Scheduler {scheduler_id}: Dispatching skipped - Emergency STOP is ACTIVE.")
            return dispatched_counts

        if emergency.is_paused:
            logger.info(f"Scheduler {scheduler_id}: Dispatching deferred - Emergency PAUSE is ACTIVE.")
            return dispatched_counts

        async with async_session_factory() as session:
            # 2. Check Paid Projects requiring Execution
            paid_stmt = (
                select(Project)
                .where(Project.status == ProjectStatus.PAID)
                .limit(50)
            )
            paid_projects = (await session.execute(paid_stmt)).scalars().all()

            for proj in paid_projects:
                # Transition to EXECUTING
                proj.status = ProjectStatus.EXECUTING
                proj.updated_at = datetime.now(timezone.utc)

                # Create and enqueue skill execution task with grounded parameters
                task_id = f"task_exec_{proj.id[:8]}_{int(datetime.now(timezone.utc).timestamp())}"
                from packages.agent.dispatcher import DispatchTaskMessage

                req_stmt = select(Requirement).where(Requirement.project_id == proj.id)
                proj_reqs = (await session.execute(req_stmt)).scalars().all()
                import re
                stated_api_url = None
                for r in proj_reqs:
                    m = re.search(r"https?://[^\s'\"]+", f"{r.title} {r.description}")
                    if m:
                        stated_api_url = m.group(0)
                        break

                client_stmt = select(Client).where(Client.id == proj.client_id)
                client_obj = (await session.execute(client_stmt)).scalar_one_or_none()
                client_domain = None
                if client_obj and client_obj.email and "@" in client_obj.email:
                    client_domain = client_obj.email.split("@")[-1].strip().lower()

                task_msg = DispatchTaskMessage(
                    task_id=task_id,
                    project_id=proj.id,
                    worker_type="skill",
                    action_name="build_n8n_automation",
                    payload={
                        "workflow_name": proj.name,
                        "webhook_path": f"/webhook/{proj.id[:8]}",
                        "crm_api_url": stated_api_url,
                        "domain": client_domain,
                    },
                    idempotency_key=f"idemp_exec_{proj.id}_{task_id}",
                    timeout_seconds=120,
                )

                # Dispatch durably to worker queue (handles DB sync + Redis streaming)
                await task_dispatcher.enqueue_task(task_msg)
                dispatched_counts["execution"] += 1
                logger.info(f"Scheduler dispatched skill execution task {task_id} for project {proj.id}")

            # 3. Advance Discovered Prospects to Qualified
            disc_stmt = (
                select(Prospect)
                .where(Prospect.status == "DISCOVERED")
                .where(Prospect.qualification_score >= 0.6)
                .limit(20)
            )
            disc_prospects = (await session.execute(disc_stmt)).scalars().all()
            for disc_p in disc_prospects:
                disc_p.status = "QUALIFIED"
                dispatched_counts["prospecting"] += 1

            # 4. Check Qualified Prospects for Outreach
            qual_stmt = (
                select(Prospect)
                .where(Prospect.status == "QUALIFIED")
                .where(Prospect.last_contacted_at.is_(None))
                .limit(20)
            )
            qual_prospects = (await session.execute(qual_stmt)).scalars().all()
            for q_p in qual_prospects:
                if not emergency.is_stopped and not emergency.is_paused:
                    contact_stmt = select(Contact).where(Contact.prospect_id == q_p.id)
                    contact = (await session.execute(contact_stmt)).scalars().first()
                    if contact and contact.email and not contact.opt_out and not q_p.opt_out:
                        pain_summary = []
                        if isinstance(q_p.pain_points, dict):
                            pts = q_p.pain_points.get("points", [])
                            obs_list = q_p.pain_points.get("observations", [])
                            if pts:
                                pain_summary.extend(pts)
                            for ob in obs_list:
                                if isinstance(ob, dict) and ob.get("statement"):
                                    pain_summary.append(ob["statement"])
                                elif hasattr(ob, "statement"):
                                    pain_summary.append(ob.statement)

                        target_name = contact.name or q_p.business_name
                        if pain_summary:
                            evidence_focus = f"Specifically, we observed integration requirements regarding: {pain_summary[0]}."
                        else:
                            evidence_focus = f"We analyzed the {q_p.industry or 'operational'} workflow infrastructure for {q_p.business_name}."

                        personalized_content = (
                            f"Hello {target_name},\n\n"
                            f"{evidence_focus}\n\n"
                            f"We engineer and deploy fixed-price autonomous backend workflows and API integrations, "
                            f"backed by 5-layer adversarial QA and delivered with full cryptographic test manifests.\n\n"
                            f"Would you be open to reviewing a scope and fixed quote for {q_p.business_name}?\n\n"
                            f"Best regards,\nAxion Autonomous Engineering"
                        )

                        from packages.tools.base import ToolRequest
                        from packages.tools.gateway import tool_gateway

                        tool_req = ToolRequest(
                            tool_name="communication.dispatch",
                            arguments={
                                "recipient": contact.email,
                                "sender": settings.SMTP_FROM_EMAIL,
                                "subject": f"Technical workflow integration: {q_p.business_name}",
                                "content": personalized_content,
                                "channel": "EMAIL",
                                "prospect_id": q_p.id,
                            },
                            requested_by_role="OPERATOR",
                            client_id=q_p.id,
                            idempotency_key=f"sched_outreach_{q_p.id}_{int(datetime.now(timezone.utc).timestamp())}",
                        )
                        tool_res = await tool_gateway.execute(tool_req)
                        if tool_res.success:
                            q_p.status = "CONTACTED"
                            q_p.last_contacted_at = datetime.now(timezone.utc)
                            dispatched_counts["outreach"] += 1
                            logger.info(f"Scheduler dispatched outreach communication to {contact.email} for prospect {q_p.id} via ToolGateway")

            await session.commit()

        return dispatched_counts

    async def run_loop(self, interval_seconds: float = SCHEDULER_INTERVAL_SECONDS) -> None:
        """Main continuous execution loop."""
        logger.info(f"Starting 24/7 Autonomous Business Scheduler {scheduler_id}...")
        await init_db()

        while running:
            try:
                # 1. Log revenue pacing
                rev_metrics = await self.calculate_weekly_revenue()
                logger.info(
                    f"[Revenue Pacing] 7d Revenue: ${rev_metrics['revenue_7d']:.2f} / "
                    f"${rev_metrics['target_weekly_revenue']:.2f} ({rev_metrics['pacing_percentage']}%) | "
                    f"Gap: ${rev_metrics['remaining_gap']:.2f}"
                )

                # 2. Run Autonomous Business Manager control cycle
                control_cycle_res = await autonomous_business_manager.run_control_cycle()
                if control_cycle_res.get("decisions_count", 0) > 0:
                    logger.info(
                        f"[Manager Cycle] Executed {control_cycle_res['decisions_count']} decisions: "
                        f"{[r['action'] for r in control_cycle_res.get('executed_results', [])]}"
                    )

                # 3. Pipeline check & task dispatch
                dispatched = await self.check_pipeline_and_dispatch()
                if any(dispatched.values()):
                    logger.info(f"[Scheduler Cycle] Dispatched tasks: {dispatched}")

            except Exception as e:
                logger.error(f"Scheduler cycle error: {e}", exc_info=True)

            # Sleep until next check interval
            await asyncio.sleep(interval_seconds)

        logger.info(f"Autonomous Scheduler {scheduler_id} shut down.")


scheduler_service = AutonomousSchedulerService()


async def main():
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    try:
        await scheduler_service.run_loop()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
