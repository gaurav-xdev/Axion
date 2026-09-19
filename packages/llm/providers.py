"""LLM provider implementations for Ollama Cloud and NVIDIA NIM.
Features centralized error handling, circuit breaking, cost estimation, and strict rate-limit reservation for NIM.
"""

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel

from packages.llm.nim_limiter import nim_limiter
from packages.observability.logger import logger
from packages.observability.metrics import NIM_REQUESTS_TOTAL, OLLAMA_REQUESTS_TOTAL
from packages.security.redaction import redact_secrets_text
from packages.shared.config import settings


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ProviderNotConfiguredError(RuntimeError):
    """Raised when an LLM provider is invoked without mandatory credentials or configuration."""
    pass


class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = CircuitBreakerState.CLOSED

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED

    def record_failure(self) -> None:
        import time
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def is_available(self) -> bool:
        import time
        if self.state == CircuitBreakerState.CLOSED:
            return True
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN allows a trial request


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass


class OllamaProvider(LLMProvider):
    """Primary LLM provider: Ollama Cloud."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.api_key = settings.OLLAMA_API_KEY
        self.model = settings.OLLAMA_MODEL
        self.circuit_breaker = CircuitBreaker()

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        if not self.circuit_breaker.is_available():
            raise RuntimeError("Ollama circuit breaker is OPEN due to repeated failures.")

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        # Fail closed if credentials or endpoint are missing
        if not self.api_key or "placeholder" in self.api_key:
            raise ProviderNotConfiguredError(
                "OllamaProvider is not configured (missing or placeholder OLLAMA_API_KEY). Synthetic fallback is prohibited."
            )

        import time
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                res.raise_for_status()
                data = res.json()

            self.circuit_breaker.record_success()
            OLLAMA_REQUESTS_TOTAL.labels(model=self.model, status="success").inc()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            latency = int((time.monotonic() - start) * 1000)

            return LLMResponse(
                content=redact_secrets_text(content),
                provider="ollama",
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=(input_tokens * 0.000001) + (output_tokens * 0.000002),
                latency_ms=latency,
            )

        except Exception as e:
            self.circuit_breaker.record_failure()
            OLLAMA_REQUESTS_TOTAL.labels(model=self.model, status="error").inc()
            logger.error(f"Ollama generation failed: {e}")
            raise

    async def health_check(self) -> bool:
        return self.circuit_breaker.is_available()


class NIMProvider(LLMProvider):
    """Secondary LLM provider: NVIDIA NIM.
    STRICT ENFORCEMENT: Every request must obtain a reservation through nim_limiter.
    """

    def __init__(self):
        self.base_url = settings.NIM_BASE_URL.rstrip("/")
        self.api_key = settings.NIM_API_KEY
        self.model = settings.NIM_MODEL
        self.circuit_breaker = CircuitBreaker()

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        if not self.circuit_breaker.is_available():
            raise RuntimeError("NVIDIA NIM circuit breaker is OPEN.")

        # CODE ENFORCEMENT: Central rate limit reservation check
        has_reservation = await nim_limiter.acquire_reservation(timeout=settings.NIM_TIMEOUT_SECONDS)
        if not has_reservation:
            NIM_REQUESTS_TOTAL.labels(model=self.model, status="rate_limited").inc()
            raise RuntimeError(
                f"NVIDIA NIM Global Hard Rate Limit ({settings.NIM_HARD_RPM_LIMIT} RPM) reached. Request rejected by code enforcement."
            )

        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
        }
        payload = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Fail closed if credentials or endpoint are missing
        if not self.api_key or "placeholder" in self.api_key:
            raise ProviderNotConfiguredError(
                "NIMProvider is not configured (missing or placeholder NIM_API_KEY). Synthetic fallback is prohibited."
            )

        import time
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.NIM_TIMEOUT_SECONDS) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                res.raise_for_status()
                data = res.json()

            self.circuit_breaker.record_success()
            NIM_REQUESTS_TOTAL.labels(model=self.model, status="success").inc()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            latency = int((time.monotonic() - start) * 1000)

            return LLMResponse(
                content=redact_secrets_text(content),
                provider="nvidia_nim",
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost=(input_tokens * 0.000005) + (output_tokens * 0.000015),
                latency_ms=latency,
            )

        except Exception as e:
            self.circuit_breaker.record_failure()
            NIM_REQUESTS_TOTAL.labels(model=self.model, status="error").inc()
            logger.error(f"NVIDIA NIM generation failed: {e}")
            raise

    async def health_check(self) -> bool:
        return self.circuit_breaker.is_available()
