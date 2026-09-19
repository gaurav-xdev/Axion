"""Application configuration using Pydantic Settings v2.
Enforces validation and type safety across all operational settings.
"""

from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Environment
    APP_ENV: str = Field(default="development")
    APP_NAME: str = Field(default="AutonomousBusinessAgent")
    APP_SECRET: str = Field(default="dev_secret_key_minimum_32_characters_long_for_security")
    API_V1_STR: str = Field(default="/api/v1")
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # Security & CORS
    CORS_ALLOWED_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:5173")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
    ADMIN_INITIAL_PASSWORD: Optional[str] = Field(default=None)

    # Database
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./workspace/agent_dev.db")
    DATABASE_POOL_SIZE: int = Field(default=20)
    DATABASE_MAX_OVERFLOW: int = Field(default=10)

    # Redis Cache / Queue
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # LLM Provider: Ollama Cloud (Primary)
    OLLAMA_BASE_URL: str = Field(default="https://api.ollama.com/v1")
    OLLAMA_API_KEY: Optional[str] = Field(default=None)
    OLLAMA_MODEL: str = Field(default="qwen2.5:72b")
    OLLAMA_TIMEOUT_SECONDS: int = Field(default=60)

    # LLM Provider: NVIDIA NIM (Secondary / Deep Reasoning)
    NIM_BASE_URL: str = Field(default="https://integrate.api.nvidia.com/v1")
    NIM_API_KEY: Optional[str] = Field(default=None)
    NIM_MODEL: str = Field(default="meta/llama-3.1-70b-instruct")
    NIM_HARD_RPM_LIMIT: int = Field(default=30)
    NIM_TARGET_RPM: int = Field(default=28)
    NIM_TIMEOUT_SECONDS: int = Field(default=90)

    # Payment: Dodo Payments
    DODO_API_KEY: Optional[str] = Field(default=None)
    DODO_WEBHOOK_SECRET: Optional[str] = Field(default=None)
    DODO_ENVIRONMENT: str = Field(default="test")
    DODO_API_URL: str = Field(default="https://test.dodopayments.com")

    # Communication Gateways
    EMAIL_ENABLED: bool = Field(default=False)
    SMTP_HOST: str = Field(default="smtp.mailgun.org")
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM_EMAIL: str = Field(default="agent@autonomousagency.local")
    SMTP_FROM_NAME: str = Field(default="Autonomous Business Agency")

    WHATSAPP_ENABLED: bool = Field(default=False)
    WHATSAPP_API_URL: str = Field(default="https://graph.facebook.com/v20.0")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="")
    WHATSAPP_ACCESS_TOKEN: str = Field(default="")
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = Field(default="")

    VOICE_ENABLED: bool = Field(default=False)
    VOICE_PROVIDER: str = Field(default="none")
    TWILIO_ACCOUNT_SID: str = Field(default="")
    TWILIO_AUTH_TOKEN: str = Field(default="")
    TWILIO_PHONE_NUMBER: str = Field(default="")

    # Storage
    STORAGE_BACKEND: str = Field(default="local")
    STORAGE_LOCAL_PATH: str = Field(default="./workspace/storage")
    S3_BUCKET: Optional[str] = Field(default=None)
    S3_REGION: Optional[str] = Field(default=None)
    S3_ACCESS_KEY: Optional[str] = Field(default=None)
    S3_SECRET_KEY: Optional[str] = Field(default=None)
    S3_ENDPOINT_URL: Optional[str] = Field(default=None)

    # Agent Guardrails & Limits
    MAX_ACTIVE_PROJECTS: int = Field(default=10)
    MAX_WORKERS: int = Field(default=8)
    MAX_BROWSER_SESSIONS: int = Field(default=4)
    MAX_TERMINAL_PROCESSES: int = Field(default=4)
    MAX_TOOL_CALLS: int = Field(default=50)
    MAX_LLM_CALLS: int = Field(default=100)
    AGENT_MAX_RUNTIME_SECONDS: int = Field(default=3600)
    AGENT_MAX_STEPS: int = Field(default=100)
    AGENT_MAX_RETRIES: int = Field(default=3)
    AGENT_MAX_COST: float = Field(default=25.0)

    # Anti-Spam & Outreach Policies
    OUTREACH_DAILY_LIMIT: int = Field(default=20)
    OUTREACH_HOURLY_LIMIT: int = Field(default=5)
    OUTREACH_COOLDOWN_DAYS: int = Field(default=30)
    MIN_PROJECT_PRICE: float = Field(default=150.0)
    MAX_DISCOUNT_PERCENT: float = Field(default=15.0)
    MIN_PROFIT_MARGIN: float = Field(default=40.0)

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]


# Global cached settings instance
settings = Settings()
