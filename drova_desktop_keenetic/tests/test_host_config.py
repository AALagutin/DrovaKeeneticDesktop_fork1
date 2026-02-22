import json
import os
import tempfile

import pytest

from drova_desktop_keenetic.common.host_config import HostConfig, StreamingConfig, load_config


def test_load_from_env_single_host(monkeypatch):
    monkeypatch.setenv("WINDOWS_HOST", "10.0.0.1")
    monkeypatch.setenv("WINDOWS_LOGIN", "admin")
    monkeypatch.setenv("WINDOWS_PASSWORD", "pass123")
    monkeypatch.setenv("SHADOW_DEFENDER_PASSWORD", "sdpass")
    monkeypatch.setenv("SHADOW_DEFENDER_DRIVES", "CD")
    monkeypatch.delenv("WINDOWS_HOSTS", raising=False)
    monkeypatch.delenv("DROVA_CONFIG", raising=False)

    config = load_config()
    assert len(config.hosts) == 1
    assert config.hosts[0].host == "10.0.0.1"
    assert config.hosts[0].login == "admin"
    assert config.hosts[0].shadow_defender_drives == "CD"
    assert config.poll_interval_idle == 5.0
    assert config.poll_interval_active == 3.0


def test_load_from_env_multi_host(monkeypatch):
    monkeypatch.setenv("WINDOWS_HOSTS", "10.0.0.1,10.0.0.2,10.0.0.3")
    monkeypatch.setenv("WINDOWS_LOGIN", "admin")
    monkeypatch.setenv("WINDOWS_PASSWORD", "pass123")
    monkeypatch.setenv("SHADOW_DEFENDER_PASSWORD", "sdpass")
    monkeypatch.setenv("SHADOW_DEFENDER_DRIVES", "C")
    monkeypatch.setenv("POLL_INTERVAL_IDLE", "10")
    monkeypatch.setenv("POLL_INTERVAL_ACTIVE", "2")
    monkeypatch.delenv("DROVA_CONFIG", raising=False)

    config = load_config()
    assert len(config.hosts) == 3
    assert config.hosts[0].host == "10.0.0.1"
    assert config.hosts[0].name == "PC-01"
    assert config.hosts[2].host == "10.0.0.3"
    assert config.hosts[2].name == "PC-03"
    assert config.poll_interval_idle == 10.0
    assert config.poll_interval_active == 2.0


def test_load_from_json(monkeypatch, tmp_path):
    config_data = {
        "poll_interval_idle": 7,
        "poll_interval_active": 2,
        "defaults": {
            "login": "admin",
            "password": "pass",
            "shadow_defender_password": "sdpass",
            "shadow_defender_drives": "CDE",
        },
        "hosts": [
            {"name": "GamePC-1", "host": "192.168.1.10"},
            {"name": "GamePC-2", "host": "192.168.1.11", "login": "other_admin"},
        ],
    }

    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))

    monkeypatch.setenv("DROVA_CONFIG", str(config_file))

    config = load_config()
    assert len(config.hosts) == 2
    assert config.hosts[0].name == "GamePC-1"
    assert config.hosts[0].login == "admin"
    assert config.hosts[1].login == "other_admin"
    assert config.poll_interval_idle == 7.0


def test_streaming_defaults_from_env(monkeypatch):
    """Env-based config has streaming disabled by default."""
    monkeypatch.setenv("WINDOWS_HOST", "10.0.0.1")
    monkeypatch.setenv("WINDOWS_LOGIN", "admin")
    monkeypatch.setenv("WINDOWS_PASSWORD", "pass")
    monkeypatch.setenv("SHADOW_DEFENDER_PASSWORD", "sdpass")
    monkeypatch.setenv("SHADOW_DEFENDER_DRIVES", "C")
    monkeypatch.delenv("WINDOWS_HOSTS", raising=False)
    monkeypatch.delenv("DROVA_CONFIG", raising=False)

    config = load_config()
    assert config.streaming.enabled is False
    assert config.streaming.fps == 2
    assert config.streaming.resolution == "1280x720"
    assert config.streaming.encoder == "h264_nvenc"


def test_streaming_loaded_from_json(monkeypatch, tmp_path):
    """Streaming section from JSON is loaded into StreamingConfig."""
    config_data = {
        "defaults": {
            "login": "admin",
            "password": "pass",
            "shadow_defender_password": "sdpass",
            "shadow_defender_drives": "C",
        },
        "hosts": [{"name": "PC-1", "host": "192.168.1.10"}],
        "streaming": {
            "enabled": True,
            "monitor_ip": "192.168.1.200",
            "monitor_port": 8554,
            "fps": 3,
            "resolution": "1920x1080",
            "bitrate": "400k",
            "encoder": "h264_nvenc",
            "encoder_preset": "p2",
            "process_priority": "BELOWNORMAL",
            "geoip_db_dir": "/opt/geoip",
            "geoip_update_interval_days": 14,
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))
    monkeypatch.setenv("DROVA_CONFIG", str(config_file))

    config = load_config()
    s = config.streaming
    assert s.enabled is True
    assert s.monitor_ip == "192.168.1.200"
    assert s.monitor_port == 8554
    assert s.fps == 3
    assert s.resolution == "1920x1080"
    assert s.bitrate == "400k"
    assert s.encoder == "h264_nvenc"
    assert s.encoder_preset == "p2"
    assert s.process_priority == "BELOWNORMAL"
    assert s.geoip_db_dir == "/opt/geoip"
    assert s.geoip_update_interval_days == 14


def test_streaming_missing_from_json_uses_defaults(monkeypatch, tmp_path):
    """JSON config without streaming section gets default StreamingConfig."""
    config_data = {
        "defaults": {
            "login": "admin",
            "password": "pass",
            "shadow_defender_password": "sdpass",
            "shadow_defender_drives": "C",
        },
        "hosts": [{"name": "PC-1", "host": "192.168.1.10"}],
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data))
    monkeypatch.setenv("DROVA_CONFIG", str(config_file))

    config = load_config()
    assert config.streaming.enabled is False
    assert config.streaming == StreamingConfig()
