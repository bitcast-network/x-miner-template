"""Application-specific settings layered on the Bitcast X protocol settings."""

from pydantic import Field
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
