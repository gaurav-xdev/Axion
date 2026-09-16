"""Context retrieval and memory management engine.
Assembles trusted internal state (database) and clearly separates untrusted external content.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select

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


class AssembledContext(BaseModel):
    project_id: Optional[str] = None
    client_name: Optional[str] = None
    project_status: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    recent_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    recent_messages: List[Dict[str, str]] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)
    untrusted_external_content: List[str] = Field(default_factory=list)


class MemoryManager:
    async def retrieve_project_context(self, project_id: str) -> AssembledContext:
        """Retrieves and partitions authoritative project context from PostgreSQL."""
        async with async_session_factory() as session:
            proj = await session.get(Project, project_id)
            if not proj:
                return AssembledContext(project_id=project_id)

            client = await session.get(Client, proj.client_id) if proj.client_id else None

            # Requirements
            req_stmt = select(Requirement).where(Requirement.project_id == project_id)
            reqs = (await session.execute(req_stmt)).scalars().all()

            # Tasks
            task_stmt = select(ProjectTask).where(ProjectTask.project_id == project_id).order_by(ProjectTask.created_at.desc()).limit(5)
            tasks = (await session.execute(task_stmt)).scalars().all()

            # Artifacts
            art_stmt = select(Artifact).where(Artifact.project_id == project_id)
            arts = (await session.execute(art_stmt)).scalars().all()

            # Messages
            conv_stmt = select(Conversation).where(Conversation.client_id == proj.client_id)
            conv = (await session.execute(conv_stmt)).scalars().first()

            messages_list = []
            if conv:
                msg_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(5)
                msgs = (await session.execute(msg_stmt)).scalars().all()
                for m in reversed(msgs):
                    messages_list.append({
                        "direction": m.direction,
                        "content": m.content,
                        "channel": m.channel.value,
                    })

            return AssembledContext(
                project_id=proj.id,
                client_name=client.name if client else "Unknown Client",
                project_status=proj.status.value,
                requirements=[f"{r.title}: {r.description}" for r in reqs],
                recent_tasks=[{"worker": t.worker_type, "status": t.status.value, "desc": t.description} for t in tasks],
                recent_messages=messages_list,
                artifacts=[f"{a.name} ({a.artifact_type})" for a in arts],
            )


# Global singleton
memory_manager = MemoryManager()
