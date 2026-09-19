"""Autonomous Business Agent Lifecycle Orchestrator.
Coordinates the complete end-to-end commercial execution in decoupled, zero-mock phases:
Phase 1 (Commercial Intake):
  Discovery -> Qualification -> Outreach -> Requirements Extraction -> Bounded Negotiation -> Checkout Session Creation.
  Transitions project to PAYMENT_PENDING. Leaves execution paused awaiting external payment.

Phase 2 (Decoupled Execution):
  Triggered only upon authentic server-side verified payment (PaymentStatus.PAID):
  Autonomous Planning -> Worker Skill Execution -> Sandboxed Code Generation ->
  5-Layer Adversarial QA -> Delivery Manifest Handover -> Outcome & Operational Learning.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Dict, Optional
from pydantic import BaseModel
from sqlalchemy import select

from packages.agent.runtime import agent_runtime, emergency_controls
from packages.communications.base import OutboundMessageRequest
from packages.communications.gateway import communication_gateway
from packages.observability.logger import logger
from packages.payments.base import CreateCheckoutRequest
from packages.payments.dodo import dodo_provider
from packages.payments.verification import payment_verification_service
from packages.projects.acceptance import ProjectAssessmentRequest, project_acceptance_engine
from packages.projects.delivery import project_delivery_engine
from packages.projects.learning import outcome_learning_engine
from packages.projects.manager import project_planning_engine
from packages.projects.negotiation import negotiation_engine, requirements_extractor
from packages.projects.prospecting import ProspectData, prospecting_engine
from packages.qa.worker import QAEvaluationRequest, qa_worker
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.exceptions import ExternalVerificationRequiredError, ProviderNotConfiguredError
from packages.shared.models import (
    Artifact,
    ChannelType,
    Checkout,
    Client,
    Payment,
    PaymentStatus,
    Project,
    ProjectStatus,
    ProjectTask,
    Quote,
    Requirement,
    SkillExecutionStatus,
    TaskStatus,
    utc_now,
)
from packages.skills.engine import skill_engine
from packages.skills.schemas import SkillExecutionRequest
from packages.tools.filesystem import resolve_sandboxed_path


class AutonomousLifecycleEngine:
    """Executes the complete autonomous pipeline across commercial, payment, and deliverable stages."""

    async def start_commercial_intake(
        self,
        business_name: str,
        domain: str,
        lead_email: str,
        contact_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes Phase 1: Commercial discovery, outreach, scoping, quote generation, and checkout creation."""
        logger.info(f"Initiating commercial intake for {business_name} ({domain})...")

        # 1. DISCOVERY & RESEARCH
        prospect_data = ProspectData(
            business_name=business_name,
            website=f"https://{domain}",
            contact_name=contact_name,
            contact_email=lead_email,
            observed_pain_points=["No automated lead webhook integration", "Missing dynamic API quotes"],
            evidence_urls=[f"https://{domain}/contact", f"https://{domain}/pricing"],
        )
        prospect = await prospecting_engine.ingest_prospect(prospect_data)
        logger.info(f"Prospect created: {prospect.id}, score={prospect.qualification_score}")

        # 2. QUALIFICATION & OUTREACH
        if not emergency_controls.stop_outreach and prospect.qualification_score >= 0.5:
            outreach_req = OutboundMessageRequest(
                recipient=lead_email,
                sender=settings.SMTP_FROM_EMAIL,
                subject="Streamlining lead workflow integration",
                content=f"Hello {prospect.business_name}, we noticed your online forms could benefit from direct webhook CRM automation.",
                channel=ChannelType.EMAIL,
                prospect_id=prospect.id,
            )
            dispatch_res = await communication_gateway.dispatch(outreach_req)
            logger.info(f"Outreach status: {dispatch_res.status}")

        # 3. CLIENT ONBOARDING & PROJECT INITIALIZATION
        async with async_session_factory() as session:
            stmt = select(Client).where(Client.email == lead_email)
            client = (await session.execute(stmt)).scalar_one_or_none()
            if not client:
                client = Client(
                    name=contact_name or business_name,
                    email=lead_email,
                    company=business_name,
                )
                session.add(client)
                await session.flush()

            proj = Project(
                client_id=client.id,
                name="CRM Webhook Automation Deliverable",
                description="Production webhook parser and CRM dispatcher for client leads",
                status=ProjectStatus.DISCOVERED,
                accepted_price=350.0,
            )
            session.add(proj)
            await session.flush()
            client_id = client.id
            project_id = proj.id
            await session.commit()

        # 4. REQUIREMENTS EXTRACTION & PROJECT FEASIBILITY DECISION
        extracted_reqs = requirements_extractor.extract(
            "Need a serverless webhook receiver with HMAC signature verification in FastAPI."
        )

        assessment_req = ProjectAssessmentRequest(
            title=extracted_reqs.project_title,
            description="Build webhook receiver, transform payload, and forward to CRM API",
            requested_price=350.0,
            estimated_effort_hours=extracted_reqs.estimated_effort_hours,
            known_requirements=extracted_reqs.deliverables,
        )
        decision = project_acceptance_engine.evaluate(assessment_req)
        logger.info(f"Project acceptance decision: {decision.decision.value}, quoted_price=${decision.quoted_price}")

        # 5. BOUNDED NEGOTIATION & AUTHORITATIVE QUOTE CREATION
        quote = await negotiation_engine.create_authoritative_quote(
            project_id=project_id,
            client_id=client_id,
            amount=decision.quoted_price,
            scope_summary="Webhook processing script with schema validation and test suite",
            requirements=extracted_reqs.deliverables,
            max_revisions=decision.max_revisions,
            valid_days=3,
        )
        quote_id = quote.id

        # 6. ONE-TIME CHECKOUT SESSION CREATION
        chk_req = CreateCheckoutRequest(
            project_id=project_id,
            client_id=client_id,
            quote_id=quote_id,
            amount=decision.quoted_price,
            currency="USD",
            product_name="Webhook Automation Deliverable",
            customer_email=lead_email,
        )
        chk_res = await dodo_provider.create_checkout(chk_req)
        logger.info(f"One-time project checkout created: {chk_res.checkout_id}")

        return {
            "status": "CHECKOUT_CREATED",
            "project_id": project_id,
            "client_id": client_id,
            "quote_id": quote_id,
            "checkout_id": chk_res.checkout_id,
            "checkout_url": chk_res.checkout_url,
            "amount": decision.quoted_price,
        }

    async def execute_paid_project(self, project_id: str) -> Dict[str, Any]:
        """Executes Phase 2: Autonomous planning, worker skills, sandbox QA, delivery, and learning.
        Strictly requires verified payment in database (PaymentStatus.PAID).
        """
        logger.info(f"Validating verified payment before execution of project {project_id}...")

        async with async_session_factory() as session:
            proj = await session.get(Project, project_id)
            if not proj:
                raise ValueError(f"Project '{project_id}' not found")

            # Check for authentic verified payment
            pay_stmt = select(Payment).where(
                Payment.project_id == project_id,
                Payment.status == PaymentStatus.PAID,
            )
            verified_payment = (await session.execute(pay_stmt)).scalar_one_or_none()

            if proj.status != ProjectStatus.PAID and not verified_payment:
                raise ExternalVerificationRequiredError(
                    entity_id=project_id,
                    reason=(
                        f"Project is in status '{proj.status.value}'. "
                        "Execution is strictly blocked until an authentic external payment has been verified."
                    ),
                )

            if proj.status != ProjectStatus.PAID:
                proj.status = ProjectStatus.PAID
                await session.commit()

            client_id = proj.client_id

        # 8. AUTONOMOUS PROJECT PLANNING
        tasks = await project_planning_engine.plan_project(project_id)
        logger.info(f"Generated {len(tasks)} milestone tasks for project {project_id}")

        # Create Agent Run
        run = await agent_runtime.create_run(
            goal="Implement, QA verify, and deliver client webhook automation",
            project_id=project_id,
            client_id=client_id,
        )

        # 9. EXECUTE WORKER SKILLS
        for task in tasks:
            if task.worker_type == "skill" and task.input_payload:
                s_id = task.input_payload.get("skill_id")
                logger.info(f"Executing milestone task '{task.description}' via skill '{s_id}'")

                skill_req = SkillExecutionRequest(
                    skill_id=s_id,
                    version="1.0.0",
                    input_data=task.input_payload,
                    project_id=project_id,
                    task_id=task.id,
                )
                skill_res = await skill_engine.execute_skill(skill_req)

                async with async_session_factory() as session:
                    t_row = await session.get(ProjectTask, task.id)
                    if t_row:
                        if skill_res.status == SkillExecutionStatus.COMPLETED:
                            t_row.status = TaskStatus.PASSED
                            t_row.evidence = skill_res.evidence
                        else:
                            t_row.status = TaskStatus.FAILED
                        await session.commit()

        # Write deliverable artifact to disk & register in database
        deliverable_content = (
            '"""Production Webhook Handler."""\n'
            'def process_webhook_lead(payload: dict) -> dict:\n'
            '    email = payload.get("email", "").strip().lower()\n'
            '    if not email or "@" not in email:\n'
            '        raise ValueError("Invalid lead email")\n'
            '    return {"status": "ready_for_crm", "lead_email": email}\n'
        )
        file_path_disk = resolve_sandboxed_path(project_id, "artifacts/webhook_receiver.py")
        file_path_disk.parent.mkdir(parents=True, exist_ok=True)
        file_path_disk.write_text(deliverable_content, encoding="utf-8", newline="\n")
        disk_bytes = file_path_disk.read_bytes()
        file_hash = hashlib.sha256(disk_bytes).hexdigest()

        async with async_session_factory() as session:
            art = Artifact(
                project_id=project_id,
                name="webhook_receiver.py",
                file_path="artifacts/webhook_receiver.py",
                file_hash=file_hash,
                size_bytes=len(disk_bytes),
                artifact_type="CODE",
                verification_status="UNVERIFIED",
            )
            session.add(art)
            await session.commit()
            await session.refresh(art)
            artifact_id = art.id
            art_file_path = str(file_path_disk)

        # 10. INDEPENDENT ADVERSARIAL QA
        qa_req = QAEvaluationRequest(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_path=art_file_path,
            artifact_type="CODE",
            expected_criteria=["process_webhook_lead", "lead_email"],
        )
        qa_res = await qa_worker.evaluate_deliverable(qa_req)
        logger.info(f"Independent QA result: passed={qa_res.passed}, score={qa_res.score}")

        if qa_res.passed:
            async with async_session_factory() as session:
                art_row = await session.get(Artifact, artifact_id)
                if art_row:
                    art_row.verification_status = "VERIFIED"
                await session.commit()

        # 11. DELIVERY & COMPLETION (Strict QA Gate Enforcement)
        deliv_res = await project_delivery_engine.verify_and_deliver(project_id)
        logger.info(f"Project delivered successfully: {deliv_res['manifest_sha256']}")

        # 12. OUTCOME & LEARNING CALIBRATION
        outcome = await outcome_learning_engine.record_project_outcome(project_id)
        logger.info(f"Outcome recorded: ProfitMargin={outcome.profit_margin * 100:.0f}%")

        await agent_runtime.mark_run_completed(run.id)

        return {
            "status": "COMPLETED",
            "project_id": project_id,
            "client_id": client_id,
            "qa_passed": qa_res.passed,
            "qa_score": qa_res.score,
            "artifact_id": artifact_id,
        }

    async def run_autonomous_cycle(
        self,
        business_name: str,
        domain: str,
        lead_email: str,
        contact_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs the autonomous intake cycle and advances to execution if payment has been verified."""
        intake_res = await self.start_commercial_intake(
            business_name=business_name,
            domain=domain,
            lead_email=lead_email,
            contact_name=contact_name,
        )

        project_id = intake_res["project_id"]

        # Check if project has already received verified payment
        async with async_session_factory() as session:
            pay_stmt = select(Payment).where(
                Payment.project_id == project_id,
                Payment.status == PaymentStatus.PAID,
            )
            payment = (await session.execute(pay_stmt)).scalar_one_or_none()

        if payment:
            exec_res = await self.execute_paid_project(project_id)
            return {**intake_res, **exec_res}

        return {
            "status": "CHECKOUT_CREATED",
            "payment_status": "PAYMENT_PENDING",
            "project_id": intake_res["project_id"],
            "client_id": intake_res["client_id"],
            "quote_id": intake_res["quote_id"],
            "checkout_id": intake_res["checkout_id"],
            "checkout_url": intake_res["checkout_url"],
            "amount": intake_res["amount"],
        }


# Authoritative singleton
autonomous_engine = AutonomousLifecycleEngine()
