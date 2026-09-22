import pytest

from app.config import Settings, get_settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "secret")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url == "sqlite+pysqlite:///:memory:"
    assert settings.jwt_secret == "secret"
    assert settings.admin_email == "admin@example.com"
    assert settings.cookie_secure is False
    assert settings.auto_create_tables is True
    assert settings.jwt_ttl_seconds == 604800
    get_settings.cache_clear()


def test_settings_require_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pass-123")
    get_settings.cache_clear()
    with pytest.raises(Exception):
        Settings(_env_file=None)
    get_settings.cache_clear()
