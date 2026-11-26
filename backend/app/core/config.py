"""Application settings with lazy loading and explicit runtime validation.

Importing this module never reads .env or fails on missing secrets so that
database-independent modules and tests can run without environment setup.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_JWT_SECRET_BYTES = 32


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

    @field_validator("database_url", "jwt_secret_key", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
