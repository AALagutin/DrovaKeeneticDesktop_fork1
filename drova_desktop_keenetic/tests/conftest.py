import pytest


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("WINDOWS_HOST", "127.0.0.1")
    monkeypatch.setenv("WINDOWS_LOGIN", "test_user")
    monkeypatch.setenv("WINDOWS_PASSWORD", "test_password")
    monkeypatch.setenv("SHADOW_DEFENDER_PASSWORD", "test_sd_pass")
    monkeypatch.setenv("SHADOW_DEFENDER_DRIVES", "C")
    monkeypatch.setenv("DROVA_SOCKET_LISTEN", "7985")
