"""Structured JSON logger with contextual correlation IDs and automatic secret redaction.
Tracks request_id, run_id, task_id, project_id, client_id, worker_id, and tool_run_id.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variables for distributed tracing correlation
ctx_request_id: ContextVar[Optional[str]] = ContextVar("ctx_request_id", default=None)
ctx_run_id: ContextVar[Optional[str]] = ContextVar("ctx_run_id", default=None)
ctx_task_id: ContextVar[Optional[str]] = ContextVar("ctx_task_id", default=None)
ctx_project_id: ContextVar[Optional[str]] = ContextVar("ctx_project_id", default=None)
ctx_client_id: ContextVar[Optional[str]] = ContextVar("ctx_client_id", default=None)
ctx_worker_id: ContextVar[Optional[str]] = ContextVar("ctx_worker_id", default=None)
ctx_tool_run_id: ContextVar[Optional[str]] = ContextVar("ctx_tool_run_id", default=None)


class StructuredJsonFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects with secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation": {
                "request_id": ctx_request_id.get(),
                "run_id": ctx_run_id.get(),
                "task_id": ctx_task_id.get(),
                "project_id": ctx_project_id.get(),
                "client_id": ctx_client_id.get(),
                "worker_id": ctx_worker_id.get(),
                "tool_run_id": ctx_tool_run_id.get(),
            },
        }

        # Include extra attributes attached to the record
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_data.update(record.extra_fields)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Central secret redaction pass
        from packages.security.redaction import redact_dict
        safe_data = redact_dict(log_data)
        return json.dumps(safe_data)


def setup_logger(name: str = "agent", level: str = "INFO") -> logging.Logger:
    """Configures and returns a structured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)

    return logger


logger = setup_logger()
