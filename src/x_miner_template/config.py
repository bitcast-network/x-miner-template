"""Configuration for the reference miner product."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Keep node and optional demo credentials in server runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="X_MINER_",
        extra="ignore",
        frozen=True,
    )

    host: str = "0.0.0.0"  # noqa: S104 - container web service
    port: int = Field(default=8080, ge=1, le=65_535)
    node_url: str = "http://127.0.0.1:8095"
    node_token: SecretStr = Field(min_length=64)
    request_timeout_seconds: float = Field(default=30, gt=0, le=300)
    web_username: str = Field(default="bitcast", min_length=1, max_length=64)
    web_password: SecretStr | None = Field(default=None, min_length=16)
