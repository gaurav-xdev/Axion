"""Smart LLM Router.
Routes prompts deterministically to Ollama Cloud (default/low-cost) or NVIDIA NIM (complex reasoning/high-risk).
Optimizes for lowest-cost adequate provider while respecting global rate limits.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from packages.llm.nim_limiter import nim_limiter
from packages.llm.providers import LLMProvider, LLMResponse, NIMProvider, OllamaProvider
from packages.observability.logger import logger


class TaskContext(BaseModel):
    task_type: str = Field(default="routine")  # routine, coding, planning, architecture, security_audit, qa
    complexity: float = Field(default=0.3, ge=0.0, le=1.0)
    ambiguity: float = Field(default=0.2, ge=0.0, le=1.0)
    risk_level: str = Field(default="LOW")  # READ_ONLY, LOW, MEDIUM, HIGH, CRITICAL
    context_size: int = Field(default=1000)
    failure_cost: float = Field(default=0.2, ge=0.0, le=1.0)


class LLMRouter:
    def __init__(self):
        self.ollama = OllamaProvider()
        self.nim = NIMProvider()

    async def route(self, context: TaskContext) -> LLMProvider:
        """Determines whether to assign task to Ollama Cloud or NVIDIA NIM based on complexity score."""
        # Calculate composite complexity score [0.0 - 1.0]
        risk_weights = {"READ_ONLY": 0.0, "LOW": 0.1, "MEDIUM": 0.3, "HIGH": 0.7, "CRITICAL": 1.0}
        risk_score = risk_weights.get(context.risk_level, 0.2)

        composite_score = (
            (context.complexity * 0.4)
            + (context.ambiguity * 0.2)
            + (risk_score * 0.2)
            + (context.failure_cost * 0.2)
        )

        # Hard criteria requiring deep reasoning (NIM)
        requires_deep_reasoning = (
            context.task_type in {"architecture", "security_audit", "complex_debugging"}
            or composite_score > 0.65
        )

        # Check NIM current window saturation
        current_nim_count = await nim_limiter.get_current_window_count()

        if requires_deep_reasoning and current_nim_count < 28:
            logger.info(
                f"Routing task '{context.task_type}' (score: {composite_score:.2f}) to NVIDIA NIM."
            )
            return self.nim

        logger.info(
            f"Routing task '{context.task_type}' (score: {composite_score:.2f}) to Ollama Cloud."
        )
        return self.ollama

    async def generate(
        self,
        messages: List[Dict[str, str]],
        context: TaskContext,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Selects provider and executes generation with graceful fallback."""
        provider = await self.route(context)
        try:
            return await provider.generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            # If NIM fails, fallback to Ollama if healthy
            if isinstance(provider, NIMProvider):
                logger.warning(f"NIM request failed ({e}). Falling back to Ollama Cloud.")
                return await self.ollama.generate(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            raise


# Global singleton router
llm_router = LLMRouter()
