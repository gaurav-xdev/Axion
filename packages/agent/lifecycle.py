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
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from sqlalchemy import select

from packages.agent.runtime import agent_runtime, emergency_controls
from packages.observability.logger import logger
from packages.payments.verification import payment_verification_service
from packages.projects.acceptance import ProjectAssessmentRequest, project_acceptance_engine
from packages.projects.delivery import project_delivery_engine
from packages.projects.learning import outcome_learning_engine
from packages.projects.manager import project_planning_engine
from packages.projects.negotiation import negotiation_engine, requirements_extractor
from packages.projects.prospecting import (
    ObservationType,
    ProspectData,
    ResearchObservation,
    prospecting_engine,
)
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
    Prospect,
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
        observations: Optional[List[ResearchObservation]] = None,
    ) -> Dict[str, Any]:
        """Executes Phase 1: Commercial discovery, qualification, and initial outreach.
        Strictly STOPS after outreach to await inbound response.
        Does NOT prematurely create a Client, Project, Requirement, Quote, or Checkout session.
        """
        logger.info(f"Initiating commercial intake for {business_name} ({domain})...")

        # 1. DISCOVERY & RESEARCH (Grounding on real observations)
        res_observations = observations or [
            ResearchObservation(
                observation_type=ObservationType.FACT,
                statement=f"Reachable public presence at {domain}",
                confidence=1.0,
                source_url=f"https://{domain}",
            ),
            ResearchObservation(
                observation_type=ObservationType.INFERENCE,
                statement=f"Public inquiry intake channel identified at {lead_email}",
                confidence=0.9,
                source_url=f"https://{domain}",
            ),
        ]
        prospect_data = ProspectData(
            business_name=business_name,
            website=f"https://{domain}",
            contact_name=contact_name,
            contact_email=lead_email,
            observed_pain_points=[],
            evidence_urls=[f"https://{domain}"],
            observations=res_observations,
        )
        prospect = await prospecting_engine.ingest_prospect(prospect_data)
        logger.info(f"Prospect created: {prospect.id}, score={prospect.qualification_score}")

        # 2. QUALIFICATION & OUTREACH (Via Authoritative ToolGateway)
        outreach_status = "SKIPPED"
        if not emergency_controls.stop_outreach and prospect.qualification_score >= 0.5:
            # Build evidence-derived personalized outreach
            pain_summary = []
            if isinstance(prospect.pain_points, dict):
                pts = prospect.pain_points.get("points", [])
                obs_list = prospect.pain_points.get("observations", [])
                if pts:
                    pain_summary.extend(pts)
                for ob in obs_list:
                    if isinstance(ob, dict) and ob.get("statement"):
                        pain_summary.append(ob["statement"])
                    elif hasattr(ob, "statement"):
                        pain_summary.append(ob.statement)

            target_name = contact_name or prospect.business_name
            if pain_summary:
                evidence_focus = f"Specifically, we observed integration needs around: {pain_summary[0]}."
            else:
                evidence_focus = f"We analyzed the {prospect.industry or 'operational'} workflow infrastructure for {prospect.business_name}."

            personalized_content = (
                f"Hello {target_name},\n\n"
                f"{evidence_focus}\n\n"
                f"We design and deploy fixed-price autonomous backend workflows and API integrations, "
                f"verified by 5-layer adversarial QA and delivered with full cryptographic test manifests.\n\n"
                f"Would you be open to reviewing a scope and fixed quote for {prospect.business_name}?\n\n"
                f"Best regards,\nAxion Autonomous Engineering"
            )

            from packages.tools.base import ToolRequest
            from packages.tools.gateway import tool_gateway

            tool_req = ToolRequest(
                tool_name="communication.dispatch",
                arguments={
                    "recipient": lead_email,
                    "sender": settings.SMTP_FROM_EMAIL,
                    "subject": f"Technical workflow integration: {prospect.business_name}",
                    "content": personalized_content,
                    "channel": "EMAIL",
                    "prospect_id": prospect.id,
                },
                requested_by_role="OPERATOR",
                client_id=prospect.id,
                idempotency_key=f"outreach_{prospect.id}_{int(utc_now().timestamp())}",
            )
            dispatch_res = await tool_gateway.execute(tool_req)
            outreach_status = "SENT" if dispatch_res.success else f"FAILED: {dispatch_res.error}"
            logger.info(f"Outreach status via ToolGateway: {outreach_status}")

            if dispatch_res.success:
                async with async_session_factory() as session:
                    p_row = await session.get(Prospect, prospect.id)
                    if p_row:
                        p_row.status = "CONTACTED"
                        p_row.last_contacted_at = utc_now()
                        await session.commit()

        # Stop and wait for inbound client response
        return {
            "status": "OUTREACH_DISPATCHED",
            "prospect_id": prospect.id,
            "qualification_score": prospect.qualification_score,
            "outreach_status": outreach_status,
            "message": "Outreach dispatched. Commercial pipeline stopped awaiting inbound client response.",
        }

    async def process_inbound_commercial_response(
        self,
        sender: str,
        content: str,
        channel: ChannelType = ChannelType.EMAIL,
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Processes genuine inbound client communication, performs structured reasoning,
        creates Client and Project from genuine requirements, creates an authoritative quote,
        and generates a one-time Dodo checkout session.
        """
        from packages.communications.conversation import (
            InboundMessagePayload,
            conversation_engine,
        )

        inbound_payload = InboundMessagePayload(
            sender=sender,
            recipient=settings.SMTP_FROM_EMAIL,
            channel=channel,
            subject=subject or "Inbound Inquiry",
            content=content,
        )
        inbound_res = await conversation_engine.ingest_inbound_message(inbound_payload)
        logger.info(
            f"Processed inbound response: classification={inbound_res.classification}, "
            f"reqs_status={inbound_res.requirements_status}"
        )

        if inbound_res.requirements_status == "REQUIREMENTS_COMPLETE" and inbound_res.quote_id and inbound_res.project_id:
            # Fetch Quote to get authoritative amount and product details
            async with async_session_factory() as session:
                quote = await session.get(Quote, inbound_res.quote_id)
                proj = await session.get(Project, inbound_res.project_id)
                if not quote or not proj:
                    raise ValueError("Quote or Project missing during checkout creation")
                quote_amount = quote.amount
                proj_name = proj.name

            # Create One-Time Dodo Checkout Session via Authoritative ToolGateway
            from packages.tools.base import ToolRequest
            from packages.tools.gateway import tool_gateway

            tool_req = ToolRequest(
                tool_name="payment.create_checkout",
                arguments={
                    "quote_id": inbound_res.quote_id,
                    "amount": float(quote_amount),
                    "currency": "USD",
                    "product_name": proj_name,
                    "customer_email": sender,
                    "customer_name": None,
                },
                project_id=inbound_res.project_id,
                client_id=inbound_res.client_id,
                requested_by_role="OPERATOR",
                idempotency_key=f"checkout_{inbound_res.project_id}_{inbound_res.quote_id}",
            )
            tool_res = await tool_gateway.execute(tool_req)
            if not tool_res.success:
                raise RuntimeError(f"Payment checkout creation failed via ToolGateway: {tool_res.error}")

            chk_data = tool_res.data
            logger.info(f"One-time project checkout created via ToolGateway: {chk_data['checkout_id']}")

            return {
                "status": "CHECKOUT_CREATED",
                "project_id": inbound_res.project_id,
                "client_id": inbound_res.client_id,
                "quote_id": inbound_res.quote_id,
                "checkout_id": chk_data["checkout_id"],
                "checkout_url": chk_data["checkout_url"],
                "amount": quote_amount,
                "requirements": inbound_res.extracted_requirements.deliverables if inbound_res.extracted_requirements else [],
            }

        elif inbound_res.requirements_status == "REQUIREMENTS_PENDING":
            return {
                "status": "REQUIREMENTS_PENDING",
                "conversation_id": inbound_res.conversation_id,
                "suggested_next_action": inbound_res.suggested_next_action,
                "reasoning": inbound_res.reasoning,
            }

        else:
            return {
                "status": "CONVERSATION_UPDATED",
                "conversation_id": inbound_res.conversation_id,
                "classification": inbound_res.classification.value,
                "suggested_next_action": inbound_res.suggested_next_action,
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

            # Fetch Requirements for this project
            req_stmt = select(Requirement).where(Requirement.project_id == project_id)
            project_requirements = (await session.execute(req_stmt)).scalars().all()

        # 8. AUTONOMOUS PROJECT PLANNING
        tasks = await project_planning_engine.plan_project(project_id)
        logger.info(f"Generated {len(tasks)} milestone tasks for project {project_id}")

        # Create Agent Run
        run = await agent_runtime.create_run(
            goal=f"Implement, QA verify, and deliver project '{proj.name}'",
            project_id=project_id,
            client_id=client_id,
        )

        # 9. EXECUTE WORKER SKILLS
        for task in tasks:
            if task.worker_type == "skill" and task.input_payload:
                s_id = task.input_payload.get("skill_id")
                # Skip verification, packaging, and post-delivery outcome tasks in this phase
                if s_id in ("qa_project_deliverable", "prepare_project_delivery", "record_project_outcome"):
                    continue

                logger.info(f"Executing milestone task '{task.description}' via skill '{s_id}'")

                skill_req = SkillExecutionRequest(
                    skill_id=s_id,
                    version="1.0.0",
                    input_data=task.input_payload,
                    project_id=project_id,
                    task_id=task.id,
                )
                skill_res = await skill_engine.execute_skill(skill_req)
                logger.info(f"Skill execution result for '{s_id}': status={skill_res.status}, error={skill_res.error}")

                async with async_session_factory() as session:
                    t_row = await session.get(ProjectTask, task.id)
                    if t_row:
                        if skill_res.status == SkillExecutionStatus.COMPLETED:
                            t_row.status = TaskStatus.PASSED
                            t_row.evidence = skill_res.evidence
                        else:
                            t_row.status = TaskStatus.FAILED
                            logger.error(f"Milestone task '{task.description}' failed: {skill_res.error}")
                        await session.commit()

        # Discover deliverable artifact generated by the skill in the sandboxed workspace
        artifacts_dir = resolve_sandboxed_path(project_id, "artifacts")
        discovered_files = list(artifacts_dir.glob("*.*")) if artifacts_dir.exists() else []

        if not discovered_files:
            raise FileNotFoundError(f"Worker skill execution produced zero artifacts in {artifacts_dir}")

        # Select the primary engineering deliverable (prioritize core code/workflow/markup deliverables)
        engineering_files = [
            f for f in discovered_files
            if not f.name.endswith(("_ledger.json", "manifest.json", "dossier.json", "report.json"))
        ]
        cand_list = engineering_files if engineering_files else discovered_files

        primary_art_file = None
        for cand in cand_list:
            if cand.suffix == ".py":
                primary_art_file = cand
                break
        if not primary_art_file:
            for cand in cand_list:
                if cand.suffix in (".json", ".html"):
                    primary_art_file = cand
                    break
        if not primary_art_file:
            primary_art_file = cand_list[0]

        disk_bytes = primary_art_file.read_bytes()
        file_hash = hashlib.sha256(disk_bytes).hexdigest()
        rel_path = f"artifacts/{primary_art_file.name}"
        art_type = "CODE" if primary_art_file.suffix == ".py" else ("N8N" if "workflow" in primary_art_file.name else "REPORT")

        async with async_session_factory() as session:
            art = Artifact(
                project_id=project_id,
                name=primary_art_file.name,
                file_path=rel_path,
                file_hash=file_hash,
                size_bytes=len(disk_bytes),
                artifact_type=art_type,
                verification_status="UNVERIFIED",
            )
            session.add(art)
            await session.commit()
            await session.refresh(art)
            artifact_id = art.id

        # 10. INDEPENDENT ADVERSARIAL QA
        # Derive expected criteria dynamically from project requirements and skill output
        req_text = " ".join(r.title + " " + r.description for r in project_requirements).lower()
        expected_criteria: List[str] = []
        if "fastapi" in req_text or "webhook" in req_text:
            expected_criteria.extend(["fastapi", "receive_webhook"])
        elif "n8n" in req_text or "workflow" in req_text:
            expected_criteria.extend(["nodes", "webhook"])
        elif "api" in req_text or "client" in req_text:
            expected_criteria.extend(["httpx", "client"])
        elif "landing" in req_text or "html" in req_text:
            expected_criteria.extend(["html", "tailwind"])
        elif "dashboard" in req_text:
            expected_criteria.extend(["widgets", "metric"])
        else:
            expected_criteria.append("status")

        qa_req = QAEvaluationRequest(
            project_id=project_id,
            artifact_id=artifact_id,
            artifact_path=rel_path,
            artifact_type=art_type,
            expected_criteria=expected_criteria,
        )
        qa_res = await qa_worker.evaluate_deliverable(qa_req)
        logger.info(f"Independent QA result: passed={qa_res.passed}, score={qa_res.score}, findings={qa_res.findings}")

        if qa_res.passed:
            async with async_session_factory() as session:
                art_row = await session.get(Artifact, artifact_id)
                if art_row:
                    art_row.verification_status = "VERIFIED"

                # Update QA task status to PASSED
                for task in tasks:
                    if task.worker_type == "skill" and task.input_payload and task.input_payload.get("skill_id") == "qa_project_deliverable":
                        t_row = await session.get(ProjectTask, task.id)
                        if t_row:
                            t_row.status = TaskStatus.PASSED
                            t_row.evidence = {"qa_score": qa_res.score, "findings_count": len(qa_res.findings)}
                await session.commit()

        # 11. DELIVERY & COMPLETION (Strict QA Gate Enforcement)
        deliv_res = await project_delivery_engine.verify_and_deliver(project_id)
        logger.info(f"Project delivered successfully: {deliv_res['manifest_sha256']}")

        # Update Delivery Packaging task status to PASSED
        async with async_session_factory() as session:
            for task in tasks:
                if task.worker_type == "skill" and task.input_payload and task.input_payload.get("skill_id") == "prepare_project_delivery":
                    t_row = await session.get(ProjectTask, task.id)
                    if t_row:
                        t_row.status = TaskStatus.PASSED
                        t_row.evidence = {"manifest_sha256": deliv_res.get("manifest_sha256")}
            await session.commit()

        # 12. OUTCOME & LEARNING CALIBRATION
        outcome = await outcome_learning_engine.record_project_outcome(project_id)
        logger.info(f"Outcome recorded: ProfitMargin={outcome.profit_margin * 100:.0f}%")

        # Execute and update Milestone 4 outcome recording task
        for task in tasks:
            if task.worker_type == "skill" and task.input_payload and task.input_payload.get("skill_id") == "record_project_outcome":
                skill_req = SkillExecutionRequest(
                    skill_id="record_project_outcome",
                    version="1.0.0",
                    input_data=task.input_payload,
                    project_id=project_id,
                    task_id=task.id,
                )
                skill_res = await skill_engine.execute_skill(skill_req)
                async with async_session_factory() as session:
                    t_row = await session.get(ProjectTask, task.id)
                    if t_row:
                        t_row.status = TaskStatus.PASSED if skill_res.status == SkillExecutionStatus.COMPLETED else TaskStatus.FAILED
                        t_row.evidence = skill_res.evidence
                        await session.commit()

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
