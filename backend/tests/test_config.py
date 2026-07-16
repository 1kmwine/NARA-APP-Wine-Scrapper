import pytest

from app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DATABASE", "d")
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("NAVER_COOKIE", "NID_AUT=x; NID_SES=y")

    settings = get_settings()

    assert settings.db_host == "db.example.com"
    assert settings.db_port == 3307
    assert settings.db_username == "u"
    assert settings.db_password == "p"
    assert settings.db_database == "d"
    assert settings.naver_client_id == "cid"
    assert settings.naver_client_secret == "csecret"
    assert settings.github_token == "ghp_test"
    assert settings.naver_cookie == "NID_AUT=x; NID_SES=y"


def test_get_settings_raises_when_github_token_missing(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DATABASE", "d")
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("NAVER_COOKIE", "x")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(KeyError):
        get_settings()


def test_get_settings_raises_when_required_env_var_missing(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DATABASE", "d")
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("NAVER_COOKIE", "x")
    monkeypatch.delenv("DB_HOST", raising=False)

    with pytest.raises(KeyError):
        get_settings()
