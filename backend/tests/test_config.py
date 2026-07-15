from app.config import get_settings


def test_get_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DATABASE", "d")
    monkeypatch.setenv("NAVER_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_CLIENT_SECRET", "csecret")

    settings = get_settings()

    assert settings.db_host == "db.example.com"
    assert settings.db_port == 3307
    assert settings.naver_client_id == "cid"
