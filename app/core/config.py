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

    # Object storage for employee photos (and, later, other uploaded
    # bytes) — see app/core/storage.py. S3-compatible (Cloudflare R2, or
    # AWS S3 itself) via these four; when any is unset (dev/test), storage
    # falls back to local disk under object_storage_local_dir, signed with
    # object_storage_signing_secret — same "None in dev -> skip/fallback"
    # shape as resend_api_key above, so the app works uploadable-photo and
    # all without real cloud credentials configured.
    object_storage_endpoint_url: str | None = None
    object_storage_bucket: str | None = None
    object_storage_access_key_id: str | None = None
    object_storage_secret_access_key: str | None = None
    object_storage_region: str = "auto"
    object_storage_local_dir: str = "./var/object-storage"
    object_storage_signing_secret: str = "change-me-in-every-real-environment-32-bytes-min"
    object_storage_signed_url_ttl_seconds: int = 300

    # How long after an employee's final settlement (termination_date) an
    # already-captured photo is purged — an employer-policy retention
    # default, not a statutory figure (NDPR requires *a* documented
    # retention schedule, not this specific number).
    employee_photo_retention_days: int = 30

    # In-process job scheduler (see app/workers/scheduler.py) — runs the
    # reminder job and recurring-bill/invoice generation daily for every
    # org, inside the same plutus-api process. railway.json only stands up
    # that one web service, so this is what makes those jobs run at all
    # instead of needing a caller to hit their endpoints on a schedule.
    # Left on by default; the test suite never triggers app startup (it
    # uses TestClient without the `with` form), so it never runs there.
    scheduler_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
