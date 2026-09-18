from backend.config import Settings


def test_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("CAMPEX_ENV", "test")
    monkeypatch.setenv("CAMPEX_SERVICE_NAME", "campex")
    monkeypatch.setenv("CAMPEX_VERSION", "0.1.0")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./storage/test.sqlite3")

    settings = Settings.from_env()

    assert settings.environment == "test"
    assert settings.service_name == "campex"
    assert settings.version == "0.1.0"
    assert settings.sqlite_path.name == "test.sqlite3"
    assert settings.camera_reconnect_seconds == 5
    assert settings.camera_test_timeout_seconds == 5
