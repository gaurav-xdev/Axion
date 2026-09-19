"""Autonomous Project Planning & Execution Manager.
Automatically decomposes funded projects into structured milestones and tasks,
maps required skills, and orchestrates execution.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import (
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

            primary_skill = self.resolve_primary_skill(project, requirements)
            logger.info(f"Resolved primary engineering skill: '{primary_skill}' for project {project_id}")

            created_tasks: List[ProjectTask] = []

            # Determine artifact path for the skill
            artifact_paths = {
                "build_n8n_automation": "artifacts/workflow.json",
                "build_webhook_integration": "artifacts/webhook_receiver.py",
                "build_api_integration": "artifacts/api_client.py",
                "build_landing_page": "artifacts/index.html",
                "build_business_dashboard": "artifacts/dashboard_spec.json",
            }
            target_artifact_path = artifact_paths.get(primary_skill, "artifacts/deliverable.json")
            target_artifact_type = "CODE" if target_artifact_path.endswith(".py") else ("N8N" if "workflow" in target_artifact_path else "REPORT")

            # MILESTONE 1: Deliverable Engineering
            task_eng = ProjectTask(
                project_id=project_id,
                worker_type="skill",
                description=f"Milestone 1: Execute engineering skill '{primary_skill}'",
                input_payload={
                    "skill_id": primary_skill,
                    "project_id": project_id,
                    "workflow_name": f"workflow_{project_id[:8]}",
                    "trigger_type": "webhook",
                    "endpoint_path": f"/webhooks/{project_id[:8]}",
                    "secret_env_var": "WEBHOOK_SECRET",
                    "target_api_name": "ClientAPI",
                    "base_url": "https://api.external.local",
                    "headline": project.name,
                    "cta_text": "Get Started",
                    "dashboard_title": project.name,
                    "metric_keys": ["revenue", "conversion_rate"],
                },
                expected_output="Verified engineering deliverable written to project workspace",
                status=TaskStatus.PENDING,
            )
            session.add(task_eng)
            created_tasks.append(task_eng)

            # MILESTONE 2: Independent Adversarial QA
            task_qa = ProjectTask(
                project_id=project_id,
                worker_type="skill",
                description=f"Milestone 2: Execute 5-layer adversarial QA on deliverable",
                input_payload={
                    "skill_id": "qa_project_deliverable",
                    "project_id": project_id,
                    "artifact_id": f"art_{project_id[:8]}",
                    "artifact_path": target_artifact_path,
                    "artifact_type": target_artifact_type,
                    "expected_criteria": [r.title for r in requirements] if requirements else ["Functional deliverable"],
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
                    "artifacts": [target_artifact_path],
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


# Authoritative singleton
project_planning_engine = ProjectPlanningEngine()
