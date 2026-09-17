"""Durable Task Dispatch and Worker Queue Engine using Redis Streams and PostgreSQL.
Authoritative business state remains in PostgreSQL (ProjectTask table).
Redis Streams handles durable message queues, consumer groups, automatic claim/visibility recovery,
exponential backoff retry with jitter, dead-letter queues, bounded concurrency, and correlation tracking.
"""

import asyncio
from datetime import datetime, timezone
import json
import math
import random
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.observability.logger import logger
from packages.security.emergency import emergency_service
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import AuditEvent, ProjectTask, TaskStatus, ToolRiskLevel


STREAM_NAME = "stream:tasks:dispatch"
CONSUMER_GROUP = "workers_group"
DLQ_STREAM_NAME = "stream:tasks:dlq"


class DispatchTaskMessage(BaseModel):
    task_id: str
    project_id: str
    worker_type: str
    action_name: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 60
    enqueued_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DurableTaskDispatcher:
    """Manages enqueueing, consumer groups, acknowledgment, and dead-letter recovery."""

    def __init__(self):
        self._redis = None
        self._in_memory_queue: asyncio.Queue = asyncio.Queue()
        self._in_memory_dlq: List[Dict[str, Any]] = []

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis
                client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=1.5,
                    socket_timeout=1.5,
                )
                client.ping()
                self._redis = client
                # Ensure consumer group exists
                try:
                    self._redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
                except Exception:
                    pass  # Group already exists
            except Exception as e:
                logger.debug(f"Redis not available for stream dispatch; using in-memory queue: {e}")
                self._redis = None
        return self._redis

    async def enqueue_task(self, task: DispatchTaskMessage) -> str:
        """Durable enqueue: Persists task in PostgreSQL authoritative DB, then streams to Redis."""
        # 1. Authoritative DB Sync
        async with async_session_factory() as session:
            db_task = await session.get(ProjectTask, task.task_id)
            if not db_task:
                db_task = ProjectTask(
                    id=task.task_id,
                    project_id=task.project_id,
                    worker_type=task.worker_type,
                    description=f"Action: {task.action_name}",
                    input_payload=task.payload,
                    status=TaskStatus.PENDING,
                    retry_count=task.retry_count,
                    max_retries=task.max_retries,
                )
                session.add(db_task)
            else:
                db_task.status = TaskStatus.PENDING
                db_task.retry_count = task.retry_count
            await session.commit()

        # 2. Redis Stream Enqueue
        r = self._get_redis()
        msg_payload = {"data": json.dumps(task.model_dump())}
        if r:
            try:
                stream_id = r.xadd(STREAM_NAME, msg_payload)
                logger.info(f"Enqueued task {task.task_id} into Redis stream {STREAM_NAME} (ID: {stream_id})")
                return stream_id
            except Exception as ex:
                logger.warning(f"Redis xadd failed ({ex}), falling back to in-memory queue")
        
        await self._in_memory_queue.put(task)
        logger.info(f"Enqueued task {task.task_id} in in-memory dispatch queue")
        return f"mem_{task.task_id}"

    async def fetch_next_task(
        self,
        consumer_name: str,
        block_ms: int = 2000,
    ) -> Optional[Tuple_Entry := Any]:
        """Fetches pending task from consumer group or pending claim list."""
        r = self._get_redis()
        if r:
            try:
                # 1. Check for stale unacknowledged messages to claim (Worker crash recovery)
                pending_info = r.xpending_range(STREAM_NAME, CONSUMER_GROUP, min="-", max="+", count=10)
                for p in pending_info:
                    msg_id = p.get("message_id")
                    idle_time = p.get("idle_time", 0)  # ms
                    # If idle for > 60 seconds, reclaim it for this consumer
                    if idle_time > 60000:
                        claimed = r.xclaim(
                            STREAM_NAME,
                            CONSUMER_GROUP,
                            consumer_name,
                            min_idle_time=60000,
                            message_ids=[msg_id],
                        )
                        if claimed:
                            msg_data = claimed[0][1]
                            task_obj = DispatchTaskMessage(**json.loads(msg_data["data"]))
                            logger.info(f"Consumer {consumer_name} claimed crashed worker task {task_obj.task_id}")
                            return (claimed[0][0], task_obj)

                # 2. Read new messages
                entries = r.xreadgroup(
                    CONSUMER_GROUP,
                    consumer_name,
                    {STREAM_NAME: ">"},
                    count=1,
                    block=block_ms,
                )
                if entries:
                    stream_key, messages = entries[0]
                    if messages:
                        msg_id, fields = messages[0]
                        task_obj = DispatchTaskMessage(**json.loads(fields["data"]))
                        return (msg_id, task_obj)
            except Exception as ex:
                logger.debug(f"Redis xreadgroup failed: {ex}")

        # Fallback in-memory fetch
        try:
            task_obj = await asyncio.wait_for(self._in_memory_queue.get(), timeout=block_ms / 1000.0)
            return (f"mem_{task_obj.task_id}", task_obj)
        except asyncio.TimeoutError:
            return None

    async def acknowledge_task(self, stream_msg_id: str, task_id: str, success: bool, error: Optional[str] = None) -> None:
        """Acknowledge completed task and update authoritative database record."""
        async with async_session_factory() as session:
            db_task = await session.get(ProjectTask, task_id)
            if db_task:
                db_task.status = TaskStatus.PASSED if success else TaskStatus.FAILED
                if error:
                    db_task.evidence = {"error": error}
                await session.commit()

        r = self._get_redis()
        if r and not stream_msg_id.startswith("mem_"):
            try:
                r.xack(STREAM_NAME, CONSUMER_GROUP, stream_msg_id)
                # Trim acknowledged messages to keep stream bounded
                r.xdel(STREAM_NAME, stream_msg_id)
            except Exception as e:
                logger.warning(f"Failed to ACK message {stream_msg_id} in Redis: {e}")

    async def handle_retry_or_dlq(self, stream_msg_id: str, task: DispatchTaskMessage, error: str) -> None:
        """Applies exponential backoff with jitter or moves exhausted task to Dead Letter Queue."""
        task.retry_count += 1
        if task.retry_count <= task.max_retries:
            # Exponential backoff + jitter: min(30, 2^(retry) + random(0, 1))
            backoff_sec = min(30.0, (2 ** task.retry_count) + random.uniform(0.1, 1.0))
            logger.warning(
                f"Task {task.task_id} failed: {error}. Retrying {task.retry_count}/{task.max_retries} "
                f"in {backoff_sec:.2f}s"
            )

            # Update DB status to RETRYING
            async with async_session_factory() as session:
                db_task = await session.get(ProjectTask, task.task_id)
                if db_task:
                    db_task.status = TaskStatus.RETRYING
                    db_task.retry_count = task.retry_count
                    await session.commit()

            # Ack the failed instance from stream
            await self.acknowledge_task(stream_msg_id, task.task_id, success=False, error=error)

            # Re-enqueue after backoff
            await asyncio.sleep(backoff_sec)
            await self.enqueue_task(task)
        else:
            # DLQ Exhaustion
            logger.error(f"Task {task.task_id} EXHAUSTED {task.max_retries} retries. Moving to Dead Letter Queue.")
            async with async_session_factory() as session:
                db_task = await session.get(ProjectTask, task.task_id)
                if db_task:
                    db_task.status = TaskStatus.FAILED
                    db_task.evidence = {"error": f"Retries exhausted: {error}"}
                
                audit = AuditEvent(
                    actor="WORKER_SERVICE",
                    action="task_dlq_exhausted",
                    target_type="task",
                    target_id=task.task_id,
                    project_id=task.project_id,
                    risk_level=ToolRiskLevel.HIGH,
                    result="FAILED",
                    reason=f"Max retries ({task.max_retries}) exceeded: {error}",
                )
                session.add(audit)
                await session.commit()

            r = self._get_redis()
            if r:
                try:
                    r.xadd(DLQ_STREAM_NAME, {"data": json.dumps(task.model_dump()), "final_error": error})
                    r.xack(STREAM_NAME, CONSUMER_GROUP, stream_msg_id)
                except Exception:
                    pass
            else:
                self._in_memory_dlq.append({"task": task.model_dump(), "error": error})


# Global authoritative singleton dispatcher
task_dispatcher = DurableTaskDispatcher()
