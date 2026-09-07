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


@lru_cache
def get_settings() -> Settings:
    return Settings()
