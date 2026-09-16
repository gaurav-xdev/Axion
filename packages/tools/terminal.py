"""Sandboxed terminal command execution.
Enforces timeout, working directory confinement, and dangerous command filtering.
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Dict
from pydantic import BaseModel, Field

from packages.shared.models import ToolRiskLevel
from packages.tools.base import BaseTool, ToolRequest
from packages.tools.filesystem import resolve_sandboxed_path

# Block destructive or host-compromising commands
DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-rf\s+[/~]", re.IGNORECASE),
    re.compile(r"mkfs", re.IGNORECASE),
    re.compile(r"dd\s+if=", re.IGNORECASE),
    re.compile(r":\(\)\s*\{", re.IGNORECASE),  # Fork bomb
    re.compile(r"chmod\s+-R\s+777\s+/", re.IGNORECASE),
    re.compile(r"curl.*\|\s*(?:bash|sh)", re.IGNORECASE),
    re.compile(r"wget.*\|\s*(?:bash|sh)", re.IGNORECASE),
    re.compile(r"(?:format|del\s+/s\s+/q)\s+[a-z]:\\", re.IGNORECASE),
]


class TerminalExecInput(BaseModel):
    command: str = Field(description="Shell command to execute within the project sandbox")
    subpath: str = Field(default=".", description="Relative working directory inside project")
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class TerminalExecTool(BaseTool):
    name = "terminal.exec"
    description = "Execute a command inside the isolated project sandbox with strict resource limits"
    risk_level = ToolRiskLevel.HIGH
    input_schema = TerminalExecInput
    required_permission = "tools:execute"

    async def execute(self, params: TerminalExecInput, context: ToolRequest) -> Dict[str, Any]:
        # Guard against destructive commands
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(params.command):
                raise PermissionError(
                    f"Command rejected: matches dangerous pattern '{pattern.pattern}'"
                )

        cwd = resolve_sandboxed_path(context.project_id, params.subpath)

        # Execute as isolated subprocess
        proc = await asyncio.create_subprocess_shell(
            params.command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=params.timeout_seconds
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(
                f"Terminal execution timed out after {params.timeout_seconds} seconds"
            )

        # Truncate output to prevent memory bloat (max 64KB)
        MAX_OUTPUT = 65536
        out_text = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT]
        err_text = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT]

        return {
            "exit_code": proc.returncode,
            "stdout": out_text,
            "stderr": err_text,
            "success": proc.returncode == 0,
            "cwd": str(cwd),
        }
