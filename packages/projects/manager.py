"""Autonomous Project Planning & Execution Manager.
Automatically decomposes funded projects into structured milestones and tasks,
maps required skills, and orchestrates execution.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Client,
    Project,
    ProjectStatus,
    ProjectTask,
    Requirement,
    TaskStatus,
    utc_now,
)


class ProjectPlanResult:
    def __init__(self, project_id: str, tasks: List[ProjectTask]):
        self.project_id = project_id
        self.tasks = tasks


class ProjectPlanningEngine:
    """Decomposes projects into structured, executable milestones and tasks."""

    def resolve_primary_skill(self, project: Project, requirements: List[Requirement]) -> str:
        """Determines the authoritative skill required based on scope and requirements."""
        text = f"{project.name} {project.description} " + " ".join(r.title + " " + r.description for r in requirements)
        text_lower = text.lower()

        if any(k in text_lower for k in ["n8n", "crm sync", "workflow automation"]):
            return "build_n8n_automation"
        elif any(k in text_lower for k in ["webhook", "hmac", "callback"]):
            return "build_webhook_integration"
        elif any(k in text_lower for k in ["api client", "rest api", "http client"]):
            return "build_api_integration"
        elif any(k in text_lower for k in ["landing page", "html", "tailwind", "frontend"]):
            return "build_landing_page"
        elif any(k in text_lower for k in ["dashboard", "metrics display", "analytics board"]):
            return "build_business_dashboard"
        elif any(k in text_lower for k in ["workflow", "automation"]):
            return "build_n8n_automation"
        else:
            return "build_n8n_automation"

    def resolve_required_skills(self, project: Project, requirements: List[Requirement]) -> List[str]:
        """Determines all engineering skills required based on scope and requirements."""
        text = f"{project.name} {project.description} " + " ".join(r.title + " " + r.description for r in requirements)
        text_lower = text.lower()
        skills: List[str] = []

        is_n8n = any(k in text_lower for k in ["n8n", "crm sync", "workflow automation"])
        if is_n8n:
            skills.append("build_n8n_automation")

        if any(k in text_lower for k in ["fastapi", "hmac", "webhook receiver", "custom webhook", "webhook"]) and not is_n8n:
            skills.append("build_webhook_integration")
        if any(k in text_lower for k in ["api client", "rest api", "http client", "httpx"]):
            skills.append("build_api_integration")
        if any(k in text_lower for k in ["landing page", "html", "tailwind", "frontend"]):
            skills.append("build_landing_page")
        if any(k in text_lower for k in ["dashboard", "metrics display", "analytics board"]):
            skills.append("build_business_dashboard")

        # Default to at least one primary skill
        if not skills:
            skills.append(self.resolve_primary_skill(project, requirements))

        return skills

    async def plan_project(self, project_id: str) -> List[ProjectTask]:
        """Creates authoritative tasks and milestones for a paid project."""
        logger.info(f"Generating autonomous project plan for project {project_id}")

        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == project_id)
            project = (await session.execute(stmt)).scalar_one_or_none()
            if not project:
                raise ValueError(f"Project '{project_id}' not found")

            if project.status not in (ProjectStatus.PAID, ProjectStatus.PLANNING, ProjectStatus.EXECUTING):
                raise ValueError(
                    f"Cannot plan project in status '{project.status.value}'. Project must be funded (PAID)."
                )

            # Update status to PLANNING
            project.status = ProjectStatus.PLANNING
            await session.flush()

            # Fetch associated requirements
            req_stmt = select(Requirement).where(Requirement.project_id == project_id)
            requirements = (await session.execute(req_stmt)).scalars().all()

            required_skills = self.resolve_required_skills(project, requirements)
            primary_skill = required_skills[0]
            logger.info(f"Resolved engineering skills: {required_skills} for project {project_id}")

            created_tasks: List[ProjectTask] = []

            # Determine artifact paths
            artifact_paths = {
                "build_n8n_automation": "artifacts/workflow.json",
                "build_webhook_integration": "artifacts/webhook_receiver.py",
                "build_api_integration": "artifacts/api_client.py",
                "build_landing_page": "artifacts/index.html",
                "build_business_dashboard": "artifacts/dashboard_spec.json",
            }
            target_artifact_path = artifact_paths.get(primary_skill, "artifacts/deliverable.json")
            target_artifact_type = "CODE" if target_artifact_path.endswith(".py") else ("N8N" if "workflow" in target_artifact_path else "REPORT")

            # Dynamic extraction from project context and requirements
            import re
            combined_desc = f"{project.name} {project.description} " + " ".join(r.description for r in requirements)
            url_match = re.search(r"https?://[^\s'\"]+", combined_desc)
            if url_match:
                resolved_base_url = url_match.group(0)
            else:
                client_stmt = select(Client).where(Client.id == project.client_id)
                client_obj = (await session.execute(client_stmt)).scalar_one_or_none()
                client_domain = None
                if client_obj and client_obj.email and "@" in client_obj.email:
                    client_domain = client_obj.email.split("@")[-1].strip().lower()
                resolved_base_url = None

            # MILESTONES: Engineering Deliverable tasks for each resolved skill
            prev_task_id: Optional[str] = None
            all_artifact_paths: List[str] = []

            for idx, skill_name in enumerate(required_skills):
                art_p = artifact_paths.get(skill_name, f"artifacts/{skill_name}.json")
                all_artifact_paths.append(art_p)

                payload = {
                    "skill_id": skill_name,
                    "project_id": project_id,
                    "workflow_name": f"workflow_{project_id[:8]}",
                    "trigger_type": "webhook",
                    "endpoint_path": f"/webhooks/{project_id[:8]}",
                    "secret_env_var": "WEBHOOK_SECRET",
                    "target_api_name": f"{project.name.replace(' ', '')}Client",
                    "base_url": resolved_base_url,
                    "crm_api_url": f"{resolved_base_url}/v1/leads" if resolved_base_url else None,
                    "domain": client_domain,
                    "headline": project.name,
                    "cta_text": "Get Started",
                    "dashboard_title": project.name,
                    "metric_keys": ["revenue", "conversion_rate"],
                }
                if prev_task_id:
                    payload["depends_on_task_id"] = prev_task_id

                task_eng = ProjectTask(
                    project_id=project_id,
                    worker_type="skill",
                    description=f"Milestone 1.{idx + 1}: Execute engineering skill '{skill_name}'",
                    input_payload=payload,
                    expected_output=f"Verified {skill_name} deliverable written to {art_p}",
                    status=TaskStatus.PENDING,
                )
                session.add(task_eng)
                created_tasks.append(task_eng)
                prev_task_id = task_eng.id

            # MILESTONE 2: Independent Adversarial QA
            task_qa = ProjectTask(
                project_id=project_id,
                worker_type="skill",
                description="Milestone 2: Execute 5-layer adversarial QA on deliverables",
                input_payload={
                    "skill_id": "qa_project_deliverable",
                    "project_id": project_id,
                    "artifact_id": f"art_{project_id[:8]}",
                    "artifact_path": target_artifact_path,
                    "artifact_type": target_artifact_type,
                    "expected_criteria": [r.title for r in requirements] if requirements else ["Functional deliverable"],
                    "all_artifact_paths": all_artifact_paths,
                },
                expected_output="5-layer QA verification passing with score >= 0.85",
                status=TaskStatus.PENDING,
            )
            session.add(task_qa)
            created_tasks.append(task_qa)

            # MILESTONE 3: Delivery Packaging & Manifest
            task_pkg = ProjectTask(
                project_id=project_id,
                worker_type="skill",
                description="Milestone 3: Package delivery bundle and cryptographic manifest",
                input_payload={
                    "skill_id": "prepare_project_delivery",
                    "project_id": project_id,
                    "artifacts": all_artifact_paths,
                },
                expected_output="Cryptographically signed delivery manifest bundle",
                status=TaskStatus.PENDING,
            )
            session.add(task_pkg)
            created_tasks.append(task_pkg)

            # MILESTONE 4: Outcome & Learning Recording
            task_outcome = ProjectTask(
                project_id=project_id,
                worker_type="skill",
                description="Milestone 4: Record project outcome and financial metrics",
                input_payload={
                    "skill_id": "record_project_outcome",
                    "project_id": project_id,
                    "outcome": "DELIVERED_SUCCESSFULLY",
                    "revenue": project.accepted_price,
                },
                expected_output="Outcome recorded in authoritative financial ledger",
                status=TaskStatus.PENDING,
            )
            session.add(task_outcome)
            created_tasks.append(task_outcome)

            # Transition project to EXECUTING
            project.status = ProjectStatus.EXECUTING
            project.started_at = utc_now()

            await session.commit()
            for t in created_tasks:
                await session.refresh(t)

            logger.info(f"Project {project_id} successfully planned with {len(created_tasks)} tasks")
            return created_tasks

    async def replan_project(
        self,
        project_id: str,
        failed_task_id: str,
        failure_reason: str,
    ) -> List[ProjectTask]:
        """Intelligently diagnoses failure, adapts plan, and registers corrective milestone tasks."""
        logger.warning(f"Replanning project {project_id} following failure of task {failed_task_id}: {failure_reason}")

        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == project_id)
            project = (await session.execute(stmt)).scalar_one_or_none()
            if not project:
                raise ValueError(f"Project '{project_id}' not found")

            failed_task = await session.get(ProjectTask, failed_task_id)
            if not failed_task:
                raise ValueError(f"Failed task '{failed_task_id}' not found")

            failed_task.status = TaskStatus.CANCELLED
            failed_task.evidence = {"failure_reason": failure_reason, "status": "SUPERSEDED_BY_REPLAN"}

            # Diagnose failure mode
            is_syntax_or_compilation = any(k in failure_reason.lower() for k in ["syntax", "compile", "parse error", "indentation"])
            is_missing_context = any(k in failure_reason.lower() for k in ["missing", "required input", "not found"])

            # Create Remediation Task
            remediation_task_id = f"task_remedy_{project_id[:8]}_{uuid.uuid4().hex[:8]}"
            if is_syntax_or_compilation:
                remedy_desc = f"Remediation: Fix code syntax and compilation error in {failed_task.description}"
                remedy_payload = {
                    **(failed_task.input_payload or {}),
                    "remediation_mode": "SYNTAX_CORRECTION",
                    "previous_error": failure_reason,
                }
            elif is_missing_context:
                remedy_desc = f"Remediation: Regenerate inputs and repair context for {failed_task.description}"
                remedy_payload = {
                    **(failed_task.input_payload or {}),
                    "remediation_mode": "CONTEXT_REPAIR",
                    "previous_error": failure_reason,
                }
            else:
                remedy_desc = f"Remediation: Re-execute with alternative parameter configuration for {failed_task.description}"
                remedy_payload = {
                    **(failed_task.input_payload or {}),
                    "remediation_mode": "ALTERNATIVE_EXECUTION",
                    "previous_error": failure_reason,
                }

            remedy_task = ProjectTask(
                id=remediation_task_id,
                project_id=project_id,
                worker_type=failed_task.worker_type,
                description=remedy_desc,
                input_payload=remedy_payload,
                expected_output="Remediated milestone deliverable passing validation",
                status=TaskStatus.PENDING,
            )
            session.add(remedy_task)

            # Record failure in memory manager
            from packages.memory.context import memory_manager
            memory_manager.record_failure_lesson(
                failure_type="MILESTONE_TASK_FAILURE",
                root_cause=failure_reason,
                context_keywords=[project.name, failed_task.description],
                prevention_rule=f"Check parameters before executing: {failed_task.description}",
                solution_verified=False,
            )

            await session.commit()
            await session.refresh(remedy_task)

            # Return updated pending tasks for project
            tasks_stmt = (
                select(ProjectTask)
                .where(ProjectTask.project_id == project_id)
                .order_by(ProjectTask.created_at.asc())
            )
            all_tasks = list((await session.execute(tasks_stmt)).scalars().all())
            logger.info(f"Project {project_id} replanned: Remediation task '{remedy_desc}' registered.")
            return all_tasks


# Authoritative singleton
project_planning_engine = ProjectPlanningEngine()
