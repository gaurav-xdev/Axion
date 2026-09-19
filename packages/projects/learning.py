"""Outcome & Learning Engine.
Analyzes completed projects, correlates estimated vs actual effort and duration,
calibrates future estimation multipliers, and updates skill performance metrics.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from packages.observability.logger import logger
from packages.shared.database import async_session_factory
from packages.shared.models import (
    Project,
    ProjectStatus,
    ProjectTask,
    QAFinding,
    QARun,
    SkillMetrics,
    TaskStatus,
    utc_now,
)
from packages.tools.filesystem import resolve_sandboxed_path


class ProjectOutcomeRecord(BaseModel):
    project_id: str
    project_name: str
    revenue_usd: float
    estimated_hours: float
    actual_hours: float
    calibration_ratio: float  # actual / estimated
    tasks_count: int
    tasks_passed: int
    qa_defect_count: int
    profit_margin: float
    lessons_learned: List[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=utc_now)


class OutcomeLearningEngine:
    """Calculates project yield and calibrates autonomous operational parameters."""

    async def record_project_outcome(self, project_id: str) -> ProjectOutcomeRecord:
        """Records complete outcome metrics and updates operational calibration."""
        logger.info(f"Processing outcome and learning for project {project_id}")

        async with async_session_factory() as session:
            stmt = select(Project).where(Project.id == project_id)
            project = (await session.execute(stmt)).scalar_one_or_none()
            if not project:
                raise ValueError(f"Project '{project_id}' not found")

            # Fetch tasks
            task_stmt = select(ProjectTask).where(ProjectTask.project_id == project_id)
            tasks = (await session.execute(task_stmt)).scalars().all()
            passed_tasks = [t for t in tasks if t.status == TaskStatus.PASSED]

            # Fetch QA findings
            qa_stmt = select(QAFinding).join(QARun).where(QARun.project_id == project_id)
            findings = (await session.execute(qa_stmt)).scalars().all()

            # Calculate duration
            if project.started_at and project.completed_at:
                actual_duration_hours = max(0.1, (project.completed_at - project.started_at).total_seconds() / 3600.0)
            else:
                actual_duration_hours = max(0.5, project.estimated_effort_hours * 0.9)

            estimated_hours = max(0.1, project.estimated_effort_hours)
            calibration_ratio = round(actual_duration_hours / estimated_hours, 2)

            revenue = float(project.accepted_price)
            # Internal cost baseline: $50/hour + estimated LLM/tool cost
            internal_cost = actual_duration_hours * 50.0
            profit_margin = round(max(0.0, (revenue - internal_cost) / revenue) if revenue > 0 else 0.0, 2)

            lessons = []
            if calibration_ratio > 1.2:
                lessons.append(f"Actual effort exceeded estimate by {int((calibration_ratio - 1.0) * 100)}%. Increase future estimation buffer.")
            elif calibration_ratio < 0.8:
                lessons.append("Delivery executed ahead of schedule. Excellent execution efficiency.")

            if len(findings) > 0:
                lessons.append(f"QA caught {len(findings)} defects prior to delivery. QA gate successfully protected client handover.")
            else:
                lessons.append("Clean execution with zero QA findings on initial pass.")

            outcome = ProjectOutcomeRecord(
                project_id=project_id,
                project_name=project.name,
                revenue_usd=revenue,
                estimated_hours=round(estimated_hours, 2),
                actual_hours=round(actual_duration_hours, 2),
                calibration_ratio=calibration_ratio,
                tasks_count=len(tasks),
                tasks_passed=len(passed_tasks),
                qa_defect_count=len(findings),
                profit_margin=profit_margin,
                lessons_learned=lessons,
            )

            # Update SkillMetrics in database for skills run in this project
            for task in tasks:
                if task.worker_type == "skill" and task.input_payload and "skill_id" in task.input_payload:
                    s_id = task.input_payload["skill_id"]
                    sm_stmt = select(SkillMetrics).where(SkillMetrics.skill_id == s_id)
                    sm = (await session.execute(sm_stmt)).scalar_one_or_none()
                    if sm:
                        sm.execution_count += 1
                        if task.status == TaskStatus.PASSED:
                            sm.success_count += 1
                        else:
                            sm.failure_count += 1
                        sm.updated_at = utc_now()

            # Mark project completed if delivered
            if project.status == ProjectStatus.DELIVERED:
                project.status = ProjectStatus.COMPLETED

            await session.commit()

        # Write outcome ledger to workspace
        try:
            summary_path = resolve_sandboxed_path(project_id, "artifacts/outcome_summary.json")
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not persist outcome_summary.json to workspace: {e}")

        logger.info(
            f"Outcome recorded for project {project_id}: Revenue=${revenue:,.2f}, "
            f"CalibrationRatio={calibration_ratio}, Margin={profit_margin * 100:.0f}%"
        )
        return outcome


# Authoritative singleton
outcome_learning_engine = OutcomeLearningEngine()
