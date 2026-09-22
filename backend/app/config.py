from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pan:pan@localhost:5432/pan"
    jwt_secret: str
    jwt_ttl_seconds: int = 604800
    cookie_secure: bool = False
    admin_email: str
    admin_password: str
    auto_create_tables: bool = False
    cookie_fernet_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
