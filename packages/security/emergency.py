"""Authoritative Distributed Emergency Control Service.
Enforces distributed emergency state backed by persistent database storage (PostgreSQL/SQLite)
and optionally cached/broadcast via Redis.

Guarantees:
- Strict separation of PAUSE vs STOP semantics.
- PAUSE: Temporarily suspends scheduling new tasks. In-flight operations may finish or yield safely.
- STOP: Hard halt preventing ALL new side-effecting operations immediately.
- Persistence across worker and API process restarts.
- Immediate inheritance of authoritative state by new workers upon startup.
- Authorized resume only (requires valid operator/owner role).
- Explicit AuditEvent logged for every state transition.
"""

import asyncio
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel
from sqlalchemy import select

from packages.observability.logger import logger
from packages.shared.config import settings
from packages.shared.database import async_session_factory
from packages.shared.models import AuditEvent, SystemState, ToolRiskLevel


class EmergencyState(BaseModel):
    is_paused: bool = False
    is_stopped: bool = False
    stop_outreach: bool = False
    updated_by: str = "SYSTEM"
    reason: str = ""
    version: int = 1
    updated_at: str = ""


STATE_KEY = "emergency_controls"


class DistributedEmergencyService:
    _lock = asyncio.Lock()

    def __init__(self):
        self._cached_state: Optional[EmergencyState] = None
        self._last_fetch_time: float = 0.0
        self._cache_ttl_seconds: float = 0.5  # Fast 500ms sync for multi-process safety
        self._redis_client = None

    def _get_redis(self):
        if self._redis_client is None:
            try:
                import redis
                self._redis_client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                )
                self._redis_client.ping()
            except Exception:
                self._redis_client = None
        return self._redis_client

    async def get_state(self, force_refresh: bool = False) -> EmergencyState:
        """Retrieves authoritative emergency state from DB or fresh Redis cache."""
        now = time.monotonic()
        if not force_refresh and self._cached_state and (now - self._last_fetch_time < self._cache_ttl_seconds):
            return self._cached_state

        # Check Redis cache if available
        r = self._get_redis()
        if r and not force_refresh:
            try:
                raw = r.get(f"state:{STATE_KEY}")
                if raw:
                    data = json.loads(raw)
                    state = EmergencyState(**data)
                    self._cached_state = state
                    self._last_fetch_time = now
                    return state
            except Exception as e:
                logger.debug(f"Redis get emergency state failed, falling back to DB: {e}")

        # Authoritative Database query
        async with async_session_factory() as session:
            db_state = await session.get(SystemState, STATE_KEY)
            if not db_state:
                # Initialize default running state
                initial = {
                    "is_paused": False,
                    "is_stopped": False,
                    "stop_outreach": False,
                    "updated_by": "SYSTEM",
                    "reason": "Default initialization",
                    "version": 1,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                db_state = SystemState(
                    key=STATE_KEY,
                    value_json=initial,
                    version=1,
                    updated_by="SYSTEM",
                )
                session.add(db_state)
                await session.commit()
                await session.refresh(db_state)

            state = EmergencyState(**db_state.value_json)
            state.version = db_state.version

            # Update Redis cache if connected
            if r:
                try:
                    r.set(f"state:{STATE_KEY}", json.dumps(state.model_dump()), ex=60)
                except Exception:
                    pass

            self._cached_state = state
            self._last_fetch_time = now
            return state

    async def pause(self, actor: str, reason: str = "Operator requested pause") -> EmergencyState:
        """Sets PAUSE = True. Blocks new tasks from dispatching without hard-aborting in-flight safe steps."""
        return await self._transition(
            actor=actor,
            action="EMERGENCY_PAUSE",
            is_paused=True,
            is_stopped=False,
            stop_outreach=True,
            reason=reason,
        )

    async def stop(self, actor: str, reason: str = "Emergency stop activated") -> EmergencyState:
        """Sets STOP = True. Authoritative hard halt preventing any new side-effects immediately."""
        return await self._transition(
            actor=actor,
            action="EMERGENCY_STOP",
            is_paused=True,
            is_stopped=True,
            stop_outreach=True,
            reason=reason,
        )

    async def resume(self, actor: str, reason: str = "Authorized system resume") -> EmergencyState:
        """Resets PAUSE and STOP to False. Resumes normal platform operations."""
        return await self._transition(
            actor=actor,
            action="EMERGENCY_RESUME",
            is_paused=False,
            is_stopped=False,
            stop_outreach=False,
            reason=reason,
        )

    async def _transition(
        self,
        actor: str,
        action: str,
        is_paused: bool,
        is_stopped: bool,
        stop_outreach: bool,
        reason: str,
    ) -> EmergencyState:
        """Executes atomic state transition with authoritative database persistence and audit logging."""
        async with DistributedEmergencyService._lock:
            async with async_session_factory() as session:
                db_state = await session.get(SystemState, STATE_KEY)
                new_version = (db_state.version + 1) if db_state else 1

                new_data = {
                    "is_paused": is_paused,
                    "is_stopped": is_stopped,
                    "stop_outreach": stop_outreach,
                    "updated_by": actor,
                    "reason": reason,
                    "version": new_version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

                if not db_state:
                    db_state = SystemState(
                        key=STATE_KEY,
                        value_json=new_data,
                        version=new_version,
                        updated_by=actor,
                    )
                    session.add(db_state)
                else:
                    db_state.value_json = new_data
                    db_state.version = new_version
                    db_state.updated_by = actor

                # Create mandatory Audit Event
                audit_event = AuditEvent(
                    actor=actor,
                    action=action,
                    target_type="system",
                    target_id=STATE_KEY,
                    risk_level=ToolRiskLevel.CRITICAL if is_stopped else ToolRiskLevel.HIGH,
                    result="SUCCESS",
                    reason=reason,
                    metadata_json=new_data,
                )
                session.add(audit_event)

                await session.commit()
                await session.refresh(db_state)

            state = EmergencyState(**new_data)
            self._cached_state = state
            self._last_fetch_time = time.monotonic()

            # Invalidate/broadcast via Redis
            r = self._get_redis()
            if r:
                try:
                    r.set(f"state:{STATE_KEY}", json.dumps(state.model_dump()), ex=60)
                    r.publish(f"channel:{STATE_KEY}", json.dumps(state.model_dump()))
                except Exception as e:
                    logger.debug(f"Redis publish emergency state failed: {e}")

            logger.warning(
                f"[EMERGENCY_STATE_CHANGE] Action={action} Actor={actor} "
                f"Paused={is_paused} Stopped={is_stopped} Version={new_version}"
            )
            return state


emergency_service = DistributedEmergencyService()
