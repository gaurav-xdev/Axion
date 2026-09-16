"""Centralized secret detection and redaction system.
Ensures secrets are NEVER written to logs, models context, or public API responses.
"""

import re
from typing import Any, Dict, List, Union

# Patterns for sensitive credentials, keys, headers, and tokens
SECRET_PATTERNS = [
    # Bearer / JWT Tokens
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*", re.IGNORECASE), r"\1[REDACTED_JWT]"),
    # General API Keys & Passwords in JSON / Key-Value
    (re.compile(r'("(?:api_key|apiKey|secret|password|token|webhook_secret|private_key)"\s*:\s*")([^"]+)(")', re.IGNORECASE), r'\1[REDACTED]\3'),
    (re.compile(r"((?:api_key|apiKey|secret|password|token|webhook_secret|private_key)\s*=\s*['\"])[^'\"]+(['\"])", re.IGNORECASE), r"\1[REDACTED]\2"),
    # NVIDIA NIM keys: nvapi-...
    (re.compile(r"nvapi-[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_NIM_KEY]"),
    # OpenAI style keys: sk-...
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    # Credit Card numbers (Luhn candidate 13-19 digits)
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_PAYMENT_CARD]"),
    # Session Cookies
    (re.compile(r"(cookie:\s*.*)(session(?:id)?=[^;]+)", re.IGNORECASE), r"\1session=[REDACTED_COOKIE]"),
]


def redact_secrets_text(text: str) -> str:
    """Scrub known secret formats and credential patterns from raw text."""
    if not text or not isinstance(text, str):
        return text
    redacted = text
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_dict(data: Union[Dict[str, Any], List[Any], Any]) -> Any:
    """Recursively scrub sensitive keys and credential patterns from structured dictionaries/lists."""
    SENSITIVE_KEY_NAMES = {
        "password",
        "hashed_password",
        "secret",
        "app_secret",
        "api_key",
        "apikey",
        "dodo_api_key",
        "dodo_webhook_secret",
        "nim_api_key",
        "ollama_api_key",
        "smtp_password",
        "twilio_auth_token",
        "whatsapp_access_token",
        "authorization",
        "cookie",
        "access_token",
        "refresh_token",
    }

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in SENSITIVE_KEY_NAMES:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = redact_dict(v)
        return sanitized
    elif isinstance(data, list):
        return [redact_dict(item) for item in data]
    elif isinstance(data, str):
        return redact_secrets_text(data)
    return data
