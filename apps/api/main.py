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
            admin_user = User(
                email="admin@autonomousagency.local",
                hashed_password=hash_password("AdminSecurePassword2026!"),
                full_name="Principal Administrator",
                role=UserRole.OWNER,
                is_active=True,
            )
            session.add(admin_user)
            await session.commit()
            logger.info("Created default system administrator account: admin@autonomousagency.local")

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
    return {
        "is_paused": emergency_controls.is_paused,
        "is_stopped": emergency_controls.is_stopped,
        "stop_outreach": emergency_controls.stop_outreach,
        "active_mode": "AUTONOMOUS",
    }


@app.post("/api/v1/agent/emergency/pause")
async def pause_agent(_: dict = Depends(require_permission("agent:pause"))):
    emergency_controls.is_paused = True
    return {"status": "Agent execution paused"}


@app.post("/api/v1/agent/emergency/stop")
async def stop_agent(_: dict = Depends(require_permission("agent:stop"))):
    emergency_controls.is_stopped = True
    return {"status": "Agent emergency stop activated"}


@app.post("/api/v1/agent/emergency/resume")
async def resume_agent(_: dict = Depends(require_permission("agent:start"))):
    emergency_controls.is_paused = False
    emergency_controls.is_stopped = False
    return {"status": "Agent execution resumed"}


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
