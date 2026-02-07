"""Runtime configuration objects."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application settings loaded from env variables and .env files."""

    model_config = SettingsConfigDict(
        env_prefix="PP_",
        env_file=".env",
        extra="ignore",
    )

    duckdb_path: str = Field(default="data/proof_please.duckdb")
