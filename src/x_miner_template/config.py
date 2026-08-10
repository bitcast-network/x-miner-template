"""Application-specific settings layered on the Bitcast X protocol settings."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    """Environment configuration owned by the web template."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="X_MINER_",
        extra="ignore",
        frozen=True,
    )

    force_commit_timeout_seconds: float = Field(default=90.0, gt=0, le=300)
    results_api_url: str = "https://bitcast-api.bitcast.network"
    results_poll_seconds: float = Field(default=30.0, ge=5.0, le=300.0)
    internal_api_token: SecretStr = Field(
        min_length=32,
        description="Bearer token required by every creator-operation API route",
    )
