"""Unit tests for Authentication, Password Hashing, JWTs, and RBAC."""

import pytest
from packages.security.auth import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from packages.security.rbac import is_permission_allowed
from packages.shared.models import UserRole


def test_argon2_password_hashing():
    pw = "SuperSecurePassword2026!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_issuance_and_verification():
    payload = {"sub": "user_123", "email": "test@example.com", "role": "OPERATOR"}
    token = create_access_token(payload)
    decoded = decode_token(token)
    assert decoded["sub"] == "user_123"
    assert decoded["role"] == "OPERATOR"
    assert "exp" in decoded


def test_rbac_permission_boundaries():
    # Owner has full access
    assert is_permission_allowed(UserRole.OWNER, "anything:unrestricted") is True

    # Operator has project read/write, but NOT system root
    assert is_permission_allowed(UserRole.OPERATOR, "projects:read") is True
    assert is_permission_allowed(UserRole.OPERATOR, "projects:write") is True
    assert is_permission_allowed(UserRole.OPERATOR, "system:root_escalation") is False

    # Auditor has read access, but NOT tool execution
    assert is_permission_allowed(UserRole.AUDITOR, "projects:read") is True
    assert is_permission_allowed(UserRole.AUDITOR, "tools:execute") is False

    # Unknown role or undefined permissions default to DENY
    assert is_permission_allowed(UserRole.WORKER_SERVICE, "payments:write") is False
