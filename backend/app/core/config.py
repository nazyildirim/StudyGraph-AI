"""Application settings with lazy loading and explicit runtime validation.

Importing this module never reads .env or fails on missing secrets so that
database-independent modules and tests can run without environment setup.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32
DEFAULT_CORS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
_ALLOWED_LLM_PROVIDERS = frozenset({"ollama", "extractive"})
_ALLOWED_RETRIEVAL_STRATEGIES = frozenset({"semantic_e5", "bm25"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def parse_cors_origins(raw_value: str) -> list[str]:
    """Validate and split a comma-separated list of explicit CORS origins."""
    origins = [item.strip() for item in raw_value.split(",") if item.strip()]
    for origin in origins:
        if origin == "*" or "*" in origin:
            raise ValueError("Wildcard CORS origins are not permitted.")
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid CORS origin: {origin!r}")
    return origins


def get_cors_origins_for_app(*, env_file: Path | None = None) -> list[str]:
    """Read CORS origins without triggering lazy Settings load.

    Precedence:
    1. Process environment variable `CORS_ALLOWED_ORIGINS` (highest priority).
    2. `.env` file in current working directory or `backend/.env` if present.
    3. `DEFAULT_CORS_ALLOWED_ORIGINS`.
    """
    env_val = os.environ.get("CORS_ALLOWED_ORIGINS")
    if env_val is not None and env_val.strip():
        return parse_cors_origins(env_val)

    candidates = (
        [env_file]
        if env_file is not None
        else [Path(".env"), Path(__file__).resolve().parents[2] / ".env"]
    )
    for candidate in candidates:
        if candidate.is_file():
            values = dotenv_values(candidate)
            file_val = values.get("CORS_ALLOWED_ORIGINS")
            if isinstance(file_val, str) and file_val.strip():
                return parse_cors_origins(file_val)

    return parse_cors_origins(DEFAULT_CORS_ALLOWED_ORIGINS)


class ConfigurationError(RuntimeError):
    """Raised when a required runtime setting is missing or invalid."""


class Settings(BaseSettings):
    """Runtime configuration loaded lazily from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str | None = Field(default=None)
    jwt_secret_key: str | None = Field(default=None)

    jwt_issuer: str = Field(default="studygraph-ai", min_length=1)
    jwt_audience: str = Field(default="studygraph-ai-api", min_length=1)
    access_token_expire_minutes: int = Field(default=30, ge=5, le=60)
    jwt_leeway_seconds: int = Field(default=0, ge=0, le=30)

    argon2_time_cost: int = Field(default=3, ge=2)
    argon2_memory_cost: int = Field(default=65536, ge=19456)
    argon2_parallelism: int = Field(default=4, ge=1)

    login_rate_limit_account_max: int = Field(default=5, ge=1)
    login_rate_limit_ip_max: int = Field(default=30, ge=1)
    login_rate_limit_window_seconds: int = Field(default=900, ge=60)
    rate_limit_max_keys: int = Field(default=10000, ge=100)

    # RAG & local LLM settings (Issue #8)
    llm_provider: str = Field(default="ollama")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen3:4b", min_length=1)
    llm_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    llm_context_window: int = Field(default=4096, ge=512, le=32768)
    llm_max_output_tokens: int = Field(default=512, ge=64, le=4096)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_extractive_fallback_enabled: bool = Field(default=True)

    embedding_model_dir: str = Field(
        default="models/multilingual-e5-small", min_length=1
    )
    retrieval_strategy: str = Field(default="semantic_e5")
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    retrieval_min_score: float = Field(default=0.81, ge=-1.0, le=1.0)

    # Upload, CORS, and bounded model concurrency (Issue #8 Phase 6)
    upload_dir: str = Field(default="uploads", min_length=1)
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    pdf_max_pages: int = Field(default=200, ge=1, le=2000)
    pdf_max_extracted_chars: int = Field(default=500_000, ge=1000)
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )
    rag_max_concurrent_model_ops: int = Field(default=2, ge=1, le=8)

    # Question bank & assessment defaults (Issue #7)
    exam_initial_question_count: int = Field(default=15, ge=1, le=100)
    exam_retest_question_count: int = Field(default=5, ge=1, le=50)
    exam_default_mastery_threshold: float = Field(default=70.0, ge=0.0, le=100.0)

    @field_validator("database_url", "jwt_secret_key", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_LLM_PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER must be one of {sorted(_ALLOWED_LLM_PROVIDERS)}."
            )
        return normalized

    @field_validator("retrieval_strategy")
    @classmethod
    def _validate_retrieval_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_RETRIEVAL_STRATEGIES:
            raise ValueError(
                "RETRIEVAL_STRATEGY must be one of "
                f"{sorted(_ALLOWED_RETRIEVAL_STRATEGIES)}."
            )
        return normalized

    @field_validator("ollama_base_url")
    @classmethod
    def _validate_ollama_loopback_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("OLLAMA_BASE_URL must use http or https.")
        if (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
            raise ValueError(
                "OLLAMA_BASE_URL must target a local loopback address "
                "(127.0.0.1, localhost, or ::1) to prevent sending course "
                "materials to external hosts."
            )
        return value.strip().rstrip("/")

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_cors_origins(cls, value: str) -> str:
        return ",".join(parse_cors_origins(value))

    def parsed_cors_origins(self) -> list[str]:
        """Return validated list of explicit allowed CORS origins."""
        return [
            item.strip()
            for item in self.cors_allowed_origins.split(",")
            if item.strip()
        ]

    def require_database_url(self) -> str:
        """Return the configured database URL or raise ConfigurationError."""
        if not self.database_url:
            raise ConfigurationError(
                "DATABASE_URL environment variable is not configured."
            )
        return self.database_url

    def require_jwt_secret_key(self) -> str:
        """Return a validated JWT signing key (>= 32 UTF-8 bytes)."""
        if not self.jwt_secret_key:
            raise ConfigurationError(
                "JWT_SECRET_KEY environment variable is not configured."
            )
        if len(self.jwt_secret_key.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise ConfigurationError(
                f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_BYTES} bytes."
            )
        return self.jwt_secret_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings (loaded lazily on first call)."""
    return Settings()
