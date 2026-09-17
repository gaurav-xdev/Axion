"""Tests verifying Dashboard API authentication:
- Authenticated requests with Bearer tokens
- Unauthenticated requests returning 401
- Token refresh with valid refresh token
- Token refresh failure with invalid token
- Logout endpoint and token lifecycle
"""

import pytest
from httpx import ASGITransport, AsyncClient
from apps.api.main import app
from packages.security.auth import create_access_token, create_refresh_token, hash_password
from packages.shared.database import async_session_factory, init_db
from packages.shared.models import User, UserRole


@pytest.mark.asyncio
async def test_dashboard_auth_flow_and_bearer_protection():
    await init_db()

    import uuid

    test_email = f"dashboard_operator_{uuid.uuid4().hex[:6]}@test.local"
    # Seed test user
    async with async_session_factory() as session:
        user = User(
            email=test_email,
            hashed_password=hash_password("SuperSecretPass123!"),
            full_name="Dashboard Operator",
            role=UserRole.OPERATOR,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated call to protected endpoint must return 401
        res_unauth = await client.get("/api/v1/agent/status")
        assert res_unauth.status_code == 401

        # 2. Login to obtain access and refresh tokens
        res_login = await client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": "SuperSecretPass123!"},
        )
        assert res_login.status_code == 200
        data = res_login.json()
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        assert data["role"] == "OPERATOR"

        # 3. Authenticated call with Bearer header succeeds
        headers = {"Authorization": f"Bearer {access_token}"}
        res_auth = await client.get("/api/v1/agent/status", headers=headers)
        assert res_auth.status_code == 200
        assert "active_mode" in res_auth.json()

        # 4. Refresh access token using refresh_token
        res_refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert res_refresh.status_code == 200
        new_access_token = res_refresh.json()["access_token"]
        assert new_access_token is not None

        # 5. Logout endpoint test
        res_logout = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_access_token}"},
        )
        assert res_logout.status_code == 200
        assert res_logout.json()["status"] == "Successfully logged out"

        # 6. Invalid refresh token failure
        res_bad_refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "malformed.invalid.token"},
        )
        assert res_bad_refresh.status_code == 401
