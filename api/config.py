from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(..., alias="DATABASE_URL")
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_jwt_secret: str | None = Field(default=None, alias="SUPABASE_JWT_SECRET")
    media_bucket: str = Field(default="opengym-media", alias="MEDIA_BUCKET")
    media_base_url: str | None = Field(default=None, alias="MEDIA_BASE_URL")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")

    @field_validator("supabase_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def uses_transaction_pooler(self) -> bool:
        return ":6543" in self.async_database_url

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer}/.well-known/jwks.json"

    @property
    def resolved_media_base_url(self) -> str:
        return (
            self.media_base_url
            or f"{self.supabase_url}/storage/v1/object/public/{self.media_bucket}"
        ).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
