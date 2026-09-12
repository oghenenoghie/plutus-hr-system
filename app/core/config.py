from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Plutus"
    environment: str = "local"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/plutus"

    jwt_secret: str = "change-me-in-every-real-environment-32-bytes-min"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 7

    # None in dev/test — payslip email dispatch is skipped (logged, not sent)
    # rather than erroring, so the rest of the app works without it configured.
    resend_api_key: str | None = None
    email_from: str = "payroll@plutus-hr.app"

    # Comma-separated, not a JSON array — a plain string is what a Railway/
    # Vercel env var editor actually makes easy to set. The frontend and API
    # are always different origins (different Vercel/Railway hosts even in
    # production), so without this every browser request — including the
    # CORS preflight OPTIONS itself — is refused before auth ever runs.
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3100"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
