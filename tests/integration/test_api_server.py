"""Integration tests for FastAPI application server, authentication, security headers, and endpoints."""

import httpx
import pytest
from sqlalchemy import select

from apps.api.main import app
from packages.security.auth import hash_password
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import User, UserRole


@pytest.fixture(autouse=True)
async def setup_test_db_and_admin():
    await init_db()
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


@pytest.mark.asyncio
async def test_fastapi_endpoints_and_auth():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Health check
        h = await client.get("/health")
        assert h.status_code == 200
        assert h.json()["status"] == "healthy"

        # 2. Metrics check
        m = await client.get("/metrics")
        assert m.status_code == 200
        assert "agent_runs_total" in m.text

        # 3. Security headers check (Directive 94)
        assert h.headers.get("x-content-type-options") == "nosniff"
        assert h.headers.get("x-frame-options") == "DENY"

        # 4. Auth login test
        login_res = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@autonomousagency.local",
                "password": "AdminSecurePassword2026!",
            },
        )
        assert login_res.status_code == 200
        tokens = login_res.json()
        assert "access_token" in tokens
        token = tokens["access_token"]

        # 5. Protected status endpoint with JWT
        headers = {"Authorization": f"Bearer {token}"}
        status_res = await client.get("/api/v1/agent/status", headers=headers)
        assert status_res.status_code == 200
        assert status_res.json()["active_mode"] == "AUTONOMOUS"

        # 6. Run full security audit endpoint
        audit_res = await client.post("/api/v1/security/run-audit", headers=headers)
        assert audit_res.status_code == 200
        audit_data = audit_res.json()
        assert audit_data["overall_secure"] is True
        assert len(audit_data["passes"]) == 5
