"""FastAPI Production Server.
Exposes REST APIs, Dodo payment webhooks, Prometheus metrics, and security middleware.
"""

from contextlib import asynccontextmanager
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import select

from packages.agent.lifecycle import autonomous_engine
from packages.agent.runtime import emergency_controls
from packages.observability.logger import ctx_request_id, logger
from packages.payments.verification import payment_verification_service
from packages.security.emergency import emergency_service
from packages.security.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_token_payload,
    hash_password,
    verify_password,
)
from packages.security.rbac import require_permission
from packages.security.worker import security_worker
from packages.shared.config import settings
from packages.shared.database import async_session_factory, close_db, init_db
from packages.shared.models import (
    AuditEvent,
    Client,
    Payment,
    Project,
    Prospect,
    User,
    UserRole,
)


from packages.skills.catalog import get_starter_skills
from packages.skills.engine import skill_engine
from packages.skills.registry import skill_registry
from packages.skills.schemas import SkillDefinitionPayload, SkillExecutionRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database schema
    logger.info("Initializing database schemas...")
    await init_db()

    # Seed initial admin user if none exists
    async with async_session_factory() as session:
        stmt = select(User).where(User.email == "admin@autonomousagency.local")
        admin = (await session.execute(stmt)).scalar_one_or_none()
        if not admin:
            initial_password = settings.ADMIN_INITIAL_PASSWORD
            if not initial_password:
                if settings.APP_ENV == "production":
                    logger.critical(
                        "CRITICAL SECURITY: ADMIN_INITIAL_PASSWORD environment variable is not configured in production. "
                        "Skipping default admin account creation to prevent unauthorized default credentials."
                    )
                else:
                    initial_password = "AdminSecurePassword2026!"

            if initial_password:
                admin_user = User(
                    email="admin@autonomousagency.local",
                    hashed_password=hash_password(initial_password),
                    full_name="Principal Administrator",
                    role=UserRole.OWNER,
                    is_active=True,
                )
                session.add(admin_user)
                await session.commit()
                logger.info("Created system administrator account: admin@autonomousagency.local")

    # Seed and publish initial canonical starter skills if missing
    try:
        starter_skills = get_starter_skills()
        for skill_payload in starter_skills:
            try:
                existing = await skill_registry.get_skill_version(
                    skill_payload.skill_id, skill_payload.version
                )
                if not existing:
                    await skill_registry.register_skill(skill_payload, actor="SYSTEM")
                    await skill_registry.publish_skill(
                        skill_payload.skill_id, skill_payload.version, actor="SYSTEM"
                    )
            except Exception as e:
                logger.debug(f"Starter skill seed check: {e}")
    except Exception as ex:
        logger.warning(f"Failed to seed starter skills: {ex}")

    yield

    # Shutdown
    logger.info("Shutting down database connections...")
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Policy (strict allowlist)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_and_tracing_middleware(request: Request, call_next):
    """Sets correlation ID and enforces security headers on every response."""
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    ctx_request_id.set(req_id)

    response: Response = await call_next(request)

    # Security Headers (Directive 94)
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; object-src 'none';"

    return response


# -------------------------------------------------------------------------
# HEALTH & OBSERVABILITY
# -------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/liveness")
async def liveness():
    return {"status": "alive"}


@app.get("/readiness")
async def readiness():
    # Verify DB connectivity
    try:
        async with async_session_factory() as session:
            await session.execute(select(1))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "error": str(e)})


@app.get("/metrics")
async def prometheus_metrics():
    return PlainTextResponse(generate_latest().decode("utf-8"))


# -------------------------------------------------------------------------
# AUTHENTICATION
# -------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    async with async_session_factory() as session:
        stmt = select(User).where(User.email == req.email)
        user = (await session.execute(stmt)).scalar_one_or_none()

        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated",
            )

        token_data = {"sub": user.id, "email": user.email, "role": user.role.value}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            role=user.role.value,
        )


class RefreshRequest(BaseModel):
    refresh_token: str


@app.post("/api/v1/auth/refresh", response_model=TokenResponse)
async def refresh_access_token(req: RefreshRequest):
    """Refreshes short-lived JWT access token using verified refresh token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: refresh token expected",
        )

    async with async_session_factory() as session:
        user = await session.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive or not found",
            )

        token_data = {"sub": user.id, "email": user.email, "role": user.role.value}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            role=user.role.value,
        )


@app.post("/api/v1/auth/logout")
async def logout(_: dict = Depends(get_current_token_payload)):
    return {"status": "Successfully logged out"}


@app.get("/api/v1/auth/me")
async def get_current_user_profile(payload: dict = Depends(get_current_token_payload)):
    async with async_session_factory() as session:
        user = await session.get(User, payload["sub"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
        }


# -------------------------------------------------------------------------
# AUTONOMOUS AGENT & CONTROLS
# -------------------------------------------------------------------------

class TriggerCycleRequest(BaseModel):
    business_name: str
    domain: str
    lead_email: str


@app.post("/api/v1/agent/run-cycle")
async def trigger_cycle(
    req: TriggerCycleRequest,
    _: dict = Depends(require_permission("agent:start")),
):
    """Triggers end-to-end commercial cycle."""
    res = await autonomous_engine.run_autonomous_cycle(
        business_name=req.business_name,
        domain=req.domain,
        lead_email=req.lead_email,
    )
    return res


@app.get("/api/v1/agent/status")
async def get_agent_status(_: dict = Depends(require_permission("agent:read"))):
    state = await emergency_service.get_state()
    return {
        "is_paused": state.is_paused,
        "is_stopped": state.is_stopped,
        "stop_outreach": state.stop_outreach,
        "active_mode": "AUTONOMOUS",
        "updated_by": state.updated_by,
        "version": state.version,
    }


@app.post("/api/v1/agent/emergency/pause")
async def pause_agent(token: dict = Depends(require_permission("agent:pause"))):
    actor = token.get("email") or token.get("sub") or "OPERATOR"
    state = await emergency_service.pause(actor=actor, reason="Operator paused via API")
    return {"status": "Agent execution paused", "version": state.version}


@app.post("/api/v1/agent/emergency/stop")
async def stop_agent(token: dict = Depends(require_permission("agent:stop"))):
    actor = token.get("email") or token.get("sub") or "OPERATOR"
    state = await emergency_service.stop(actor=actor, reason="Emergency stop activated via API")
    return {"status": "Agent emergency stop activated", "version": state.version}


@app.post("/api/v1/agent/emergency/resume")
async def resume_agent(token: dict = Depends(require_permission("agent:start"))):
    actor = token.get("email") or token.get("sub") or "OPERATOR"
    state = await emergency_service.resume(actor=actor, reason="Authorized resume via API")
    return {"status": "Agent execution resumed", "version": state.version}


# -------------------------------------------------------------------------
# PROJECTS & PROSPECTS
# -------------------------------------------------------------------------

@app.get("/api/v1/projects")
async def list_projects(_: dict = Depends(require_permission("projects:read"))):
    async with async_session_factory() as session:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(50)
        projs = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "client_id": p.client_id,
                "status": p.status.value,
                "accepted_price": p.accepted_price,
                "created_at": p.created_at.isoformat(),
            }
            for p in projs
        ]


@app.get("/api/v1/prospects")
async def list_prospects(_: dict = Depends(require_permission("prospects:read"))):
    async with async_session_factory() as session:
        stmt = select(Prospect).order_by(Prospect.created_at.desc()).limit(50)
        prospects = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": p.id,
                "business_name": p.business_name,
                "domain": p.domain,
                "qualification_score": p.qualification_score,
                "status": p.status,
                "opt_out": p.opt_out,
                "created_at": p.created_at.isoformat(),
            }
            for p in prospects
        ]


@app.get("/api/v1/payments")
async def list_payments(_: dict = Depends(require_permission("payments:read"))):
    async with async_session_factory() as session:
        stmt = select(Payment).order_by(Payment.created_at.desc()).limit(50)
        payments = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": pay.id,
                "project_id": pay.project_id,
                "amount": pay.amount,
                "currency": pay.currency,
                "status": pay.status.value,
                "verified_at": pay.verified_at.isoformat(),
            }
            for pay in payments
        ]


# -------------------------------------------------------------------------
# SECURITY AUDIT & AUDIT LOGS
# -------------------------------------------------------------------------

@app.post("/api/v1/security/run-audit")
async def run_security_audit(_: dict = Depends(require_permission("audit:read"))):
    report = await security_worker.run_full_security_audit()
    return report


@app.get("/api/v1/audit")
async def list_audit_logs(_: dict = Depends(require_permission("audit:read"))):
    async with async_session_factory() as session:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(50)
        events = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": e.id,
                "actor": e.actor,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "result": e.result,
                "risk_level": e.risk_level.value,
                "reason": e.reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]


# -------------------------------------------------------------------------
# DODO PAYMENTS WEBHOOK ENDPOINT
# -------------------------------------------------------------------------

@app.post("/webhooks/dodo")
async def dodo_webhook_receiver(
    request: Request,
    webhook_signature: Optional[str] = Header(None, alias="webhook-signature"),
):
    """Authoritative Dodo Payments Webhook Endpoint.
    Strictly verifies HMAC-SHA256 signature and deduplicates events.
    """
    raw_body = await request.body()
    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload")

    if not webhook_signature:
        raise HTTPException(status_code=401, detail="Missing webhook-signature header")

    success, msg = await payment_verification_service.process_webhook(
        raw_body=raw_body,
        signature=webhook_signature,
        event_data=event_data,
    )

    if not success:
        raise HTTPException(status_code=400, detail=msg)

    return {"status": "accepted", "message": msg}


# -------------------------------------------------------------------------
# INBOUND COMMUNICATIONS WEBHOOK ENDPOINT
# -------------------------------------------------------------------------

@app.post("/webhooks/communications/inbound")
async def inbound_communication_webhook(
    request: Request,
):
    """Ingests inbound client communications (email / webhook / chat).
    Processes message through ConversationEngine with intent classification and state transition.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    from packages.communications.conversation import InboundMessagePayload, conversation_engine
    from packages.shared.models import ChannelType

    sender = body.get("sender") or body.get("from") or body.get("email")
    content = body.get("content") or body.get("text") or body.get("body")
    recipient = body.get("recipient") or body.get("to") or settings.SMTP_FROM_EMAIL
    channel_str = body.get("channel", "EMAIL").upper()
    channel = ChannelType[channel_str] if channel_str in ChannelType.__members__ else ChannelType.EMAIL

    if not sender or not content:
        raise HTTPException(status_code=422, detail="Missing required 'sender' or 'content' in message payload")

    payload = InboundMessagePayload(
        sender=str(sender),
        recipient=str(recipient),
        channel=channel,
        content=str(content),
        subject=body.get("subject"),
    )

    result = await conversation_engine.ingest_inbound_message(payload)
    return {
        "status": "processed",
        "conversation_id": result.conversation_id,
        "classification": result.classification.value,
        "response_sent": result.response_sent,
        "suggested_next_action": result.suggested_next_action,
    }



# -------------------------------------------------------------------------
# SKILL REGISTRY & EXECUTION ENDPOINTS
# -------------------------------------------------------------------------

@app.get("/api/v1/skills")
async def list_skills(
    category: Optional[str] = None,
    status_filter: Optional[str] = None,
    payload: dict = Depends(require_permission("skills:read")),
):
    """List registered skills with optional category and status filters."""
    s_filter = None
    if status_filter:
        try:
            from packages.shared.models import SkillStatus
            s_filter = SkillStatus(status_filter)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid status filter '{status_filter}'")

    skills = await skill_registry.list_skills(category=category, status=s_filter)
    return [
        {
            "id": s.id,
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "purpose": s.purpose,
            "version": s.version,
            "status": s.status.value,
            "allowed_tools": s.allowed_tool_names,
            "risk_class": s.risk_class.value,
            "estimated_effort": s.estimated_effort,
            "expected_duration_seconds": s.expected_duration_seconds,
            "published_at": s.published_at.isoformat() if s.published_at else None,
            "created_at": s.created_at.isoformat(),
        }
        for s in skills
    ]


@app.get("/api/v1/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    version: Optional[str] = None,
    payload: dict = Depends(require_permission("skills:read")),
):
    """Fetch exact or latest compatible skill version with full procedure, schemas, and metrics."""
    try:
        if version:
            skill = await skill_registry.get_skill_version(skill_id, version)
            if not skill:
                raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' v{version} not found")
        else:
            skill = await skill_registry.resolve_compatible_skill(skill_id)
    except Exception as ex:
        raise HTTPException(status_code=404, detail=str(ex))

    # Fetch associated metrics
    async with async_session_factory() as session:
        from packages.shared.models import SkillMetrics
        stmt = select(SkillMetrics).where(
            SkillMetrics.skill_id == skill.skill_id,
            SkillMetrics.version == skill.version,
        )
        metrics = (await session.execute(stmt)).scalar_one_or_none()

    return {
        "id": skill.id,
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "purpose": skill.purpose,
        "version": skill.version,
        "status": skill.status.value,
        "input_schema": skill.input_schema,
        "output_schema": skill.output_schema,
        "prerequisites": skill.prerequisites,
        "required_capabilities": skill.required_capabilities,
        "allowed_tools": skill.allowed_tool_names,
        "procedure": skill.procedure,
        "verification_procedure": skill.verification_procedure,
        "failure_modes": skill.failure_modes,
        "risk_class": skill.risk_class.value,
        "metrics": {
            "execution_count": metrics.execution_count if metrics else 0,
            "success_count": metrics.success_count if metrics else 0,
            "failure_count": metrics.failure_count if metrics else 0,
            "total_duration_ms": metrics.total_duration_ms if metrics else 0,
        } if metrics else None,
        "published_at": skill.published_at.isoformat() if skill.published_at else None,
        "created_at": skill.created_at.isoformat(),
    }


@app.get("/api/v1/skills/{skill_id}/versions")
async def list_skill_versions(
    skill_id: str,
    payload: dict = Depends(require_permission("skills:read")),
):
    """List all versions of a specific skill."""
    skills = await skill_registry.list_skill_versions(skill_id)
    return [
        {
            "id": s.id,
            "version": s.version,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
            "published_at": s.published_at.isoformat() if s.published_at else None,
        }
        for s in skills
    ]


@app.post("/api/v1/skills/validate")
async def validate_skill(
    skill_data: SkillDefinitionPayload,
    payload: dict = Depends(require_permission("skills:read")),
):
    """Static validation check of a skill definition payload."""
    res = await skill_registry.validate_skill_payload(skill_data)
    return res


@app.post("/api/v1/skills")
async def create_skill(
    skill_data: SkillDefinitionPayload,
    payload: dict = Depends(require_permission("skills:write")),
):
    """Register a new draft skill definition."""
    try:
        actor = payload.get("sub", "OPERATOR")
        skill = await skill_registry.register_skill(skill_data, actor=actor)
        return {
            "id": skill.id,
            "skill_id": skill.skill_id,
            "version": skill.version,
            "status": skill.status.value,
            "message": "Skill registered successfully in DRAFT status",
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/v1/skills/{skill_id}/publish")
async def publish_skill(
    skill_id: str,
    version: str,
    payload: dict = Depends(require_permission("skills:publish")),
):
    """Publish a draft skill. Once published, definition is immutable."""
    try:
        actor = payload.get("sub", "OPERATOR")
        skill = await skill_registry.publish_skill(skill_id, version, actor=actor)
        return {
            "skill_id": skill.skill_id,
            "version": skill.version,
            "status": skill.status.value,
            "published_at": skill.published_at.isoformat(),
        }
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/v1/skills/{skill_id}/deprecate")
async def deprecate_skill(
    skill_id: str,
    version: str,
    payload: dict = Depends(require_permission("skills:write")),
):
    """Deprecate a skill version."""
    try:
        actor = payload.get("sub", "OPERATOR")
        skill = await skill_registry.deprecate_skill(skill_id, version, actor=actor)
        return {"skill_id": skill.skill_id, "version": skill.version, "status": skill.status.value}
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/v1/skills/{skill_id}/disable")
async def disable_skill(
    skill_id: str,
    version: str,
    payload: dict = Depends(require_permission("skills:write")),
):
    """Disable a skill version immediately."""
    try:
        actor = payload.get("sub", "OPERATOR")
        skill = await skill_registry.disable_skill(skill_id, version, actor=actor)
        return {"skill_id": skill.skill_id, "version": skill.version, "status": skill.status.value}
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@app.post("/api/v1/skill-executions")
async def trigger_skill_execution(
    req: SkillExecutionRequest,
    payload: dict = Depends(require_permission("skills:execute")),
):
    """Execute a skill within authoritative emergency, RBAC, and ToolGateway limits."""
    actor_role = payload.get("role", "OPERATOR")
    actor_email = payload.get("sub") or payload.get("email")
    if not actor_email:
        raise HTTPException(status_code=401, detail="Token missing subject identity")
    result = await skill_engine.execute_skill(req, actor_role=actor_role, actor_email=actor_email)
    return result.model_dump()


@app.get("/api/v1/skill-executions/{execution_id}")
async def get_skill_execution(
    execution_id: str,
    payload: dict = Depends(require_permission("skills:read")),
):
    """Fetch status, current step, evidence, and outcome of a skill execution."""
    async with async_session_factory() as session:
        from packages.shared.models import SkillExecution
        exec_row = await session.get(SkillExecution, execution_id)
        if not exec_row:
            raise HTTPException(status_code=404, detail=f"Skill execution '{execution_id}' not found")

        return {
            "execution_id": exec_row.id,
            "skill_id": exec_row.skill_id,
            "version": exec_row.version,
            "status": exec_row.status.value,
            "current_step": exec_row.current_step,
            "max_steps": exec_row.max_steps,
            "input_payload": exec_row.input_payload,
            "output_payload": exec_row.output_payload,
            "evidence": exec_row.evidence,
            "metrics": exec_row.metrics_json,
            "error": exec_row.error,
            "failure_class": exec_row.failure_class.value if exec_row.failure_class else None,
            "started_at": exec_row.started_at.isoformat() if exec_row.started_at else None,
            "completed_at": exec_row.completed_at.isoformat() if exec_row.completed_at else None,
        }

