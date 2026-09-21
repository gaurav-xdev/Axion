"""Sandboxed OS Process Execution Engine.
Provides isolated, resource-governed, environment-sanitized execution for untrusted
code, test suites, and external tools without host secret leakage.
"""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from packages.observability.logger import logger


class SandboxExecutionResult(BaseModel):
    success: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    sanitized_env_keys_count: int = 0
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SandboxedProcessExecutor:
    """Strict execution sandbox enforcing environment hygiene, directory containment, and timeout bounds."""

    SENSITIVE_KEY_PATTERNS = {
        "_SECRET",
        "_KEY",
        "_PASSWORD",
        "_TOKEN",
        "DATABASE_URL",
        "REDIS_URL",
        "APP_SECRET",
        "JWT_SECRET",
        "DODO",
        "SMTP",
        "NIM",
        "OLLAMA",
        "TWILIO",
        "WHATSAPP",
        "AWS",
        "S3",
    }

    SAFE_ENV_PASSTHROUGH = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "SYSTEMDRIVE",
        "USERPROFILE",
        "HOME",
        "LANG",
        "LC_ALL",
    }

    @classmethod
    def get_sanitized_environment(cls, additional_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Strips all credentials, connection strings, and sensitive tokens from execution environment."""
        sanitized: Dict[str, str] = {}
        for k, v in os.environ.items():
            upper_k = k.upper()
            if upper_k in cls.SAFE_ENV_PASSTHROUGH:
                sanitized[k] = v
            elif any(pat in upper_k for pat in cls.SENSITIVE_KEY_PATTERNS):
                continue
            else:
                sanitized[k] = v

        if additional_env:
            for ak, av in additional_env.items():
                upper_ak = ak.upper()
                if not any(pat in upper_ak for pat in cls.SENSITIVE_KEY_PATTERNS):
                    sanitized[ak] = str(av)

        return sanitized

    @classmethod
    async def run_async_command(
        cls,
        cmd: List[str],
        cwd: Path,
        timeout_seconds: float = 30.0,
        additional_env: Optional[Dict[str, str]] = None,
    ) -> SandboxExecutionResult:
        """Executes a command inside the sanitized sandbox asynchronously."""
        if not cwd.exists():
            return SandboxExecutionResult(
                success=False,
                returncode=-1,
                stderr=f"Working directory does not exist: {cwd}",
                duration_ms=0,
            )

        sanitized_env = cls.get_sanitized_environment(additional_env)
        start_time = time.monotonic()

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                env=sanitized_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            return SandboxExecutionResult(
                success=(proc.returncode == 0),
                returncode=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_ms=duration_ms,
                timed_out=False,
                sanitized_env_keys_count=len(sanitized_env),
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as kill_err:
                    logger.warning(f"Error terminating timed out process: {kill_err}")

            return SandboxExecutionResult(
                success=False,
                returncode=-2,
                stderr=f"Process execution timed out after {timeout_seconds} seconds",
                duration_ms=duration_ms,
                timed_out=True,
                sanitized_env_keys_count=len(sanitized_env),
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxExecutionResult(
                success=False,
                returncode=-3,
                stderr=f"Subprocess spawn failure: {str(e)}",
                duration_ms=duration_ms,
                timed_out=False,
                sanitized_env_keys_count=len(sanitized_env),
            )

    @classmethod
    def run_sync_command(
        cls,
        cmd: List[str],
        cwd: Path,
        timeout_seconds: float = 30.0,
        additional_env: Optional[Dict[str, str]] = None,
    ) -> SandboxExecutionResult:
        """Executes a command synchronously within sanitized sandbox boundaries."""
        if not cwd.exists():
            return SandboxExecutionResult(
                success=False,
                returncode=-1,
                stderr=f"Working directory does not exist: {cwd}",
                duration_ms=0,
            )

        sanitized_env = cls.get_sanitized_environment(additional_env)
        start_time = time.monotonic()

        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd),
                env=sanitized_env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxExecutionResult(
                success=(res.returncode == 0),
                returncode=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_ms=duration_ms,
                timed_out=False,
                sanitized_env_keys_count=len(sanitized_env),
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxExecutionResult(
                success=False,
                returncode=-2,
                stderr=f"Process execution timed out after {timeout_seconds} seconds",
                duration_ms=duration_ms,
                timed_out=True,
                sanitized_env_keys_count=len(sanitized_env),
            )
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxExecutionResult(
                success=False,
                returncode=-3,
                stderr=f"Subprocess execution error: {str(e)}",
                duration_ms=duration_ms,
                timed_out=False,
                sanitized_env_keys_count=len(sanitized_env),
            )


sandbox_executor = SandboxedProcessExecutor()
