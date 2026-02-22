"""Tests for scripts/deploy.py — host loading, arg building, deploy orchestration."""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.deploy import (
    DeployResult,
    HostEntry,
    _build_extra_args,
    deploy_one,
    load_hosts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(skip_ffmpeg=False, sd_installer="", sd_password="", hosts=None, parallel=10)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# load_hosts — environment variables
# ---------------------------------------------------------------------------

def test_load_hosts_single_from_env(monkeypatch):
    monkeypatch.setenv("WINDOWS_HOST", "192.168.0.10")
    monkeypatch.setenv("WINDOWS_LOGIN", "admin")
    monkeypatch.setenv("WINDOWS_PASSWORD", "pass")
    monkeypatch.delenv("DROVA_CONFIG", raising=False)
    monkeypatch.delenv("WINDOWS_HOSTS", raising=False)

    hosts = load_hosts()
    assert len(hosts) == 1
    assert hosts[0].host == "192.168.0.10"
    assert hosts[0].login == "admin"
    assert hosts[0].name == "PC-01"


def test_load_hosts_multi_from_env(monkeypatch):
    monkeypatch.setenv("WINDOWS_HOSTS", "192.168.0.10,192.168.0.11,192.168.0.12")
    monkeypatch.setenv("WINDOWS_LOGIN", "admin")
    monkeypatch.setenv("WINDOWS_PASSWORD", "pass")
    monkeypatch.delenv("DROVA_CONFIG", raising=False)

    hosts = load_hosts()
    assert len(hosts) == 3
    assert hosts[2].host == "192.168.0.12"
    assert hosts[2].name == "PC-03"


# ---------------------------------------------------------------------------
# load_hosts — JSON config
# ---------------------------------------------------------------------------

def test_load_hosts_from_json(monkeypatch, tmp_path):
    config = {
        "defaults": {"login": "admin", "password": "pass"},
        "hosts": [
            {"name": "Зал1-01", "host": "192.168.0.10"},
            {"name": "Зал1-02", "host": "192.168.0.11"},
        ],
    }
    f = tmp_path / "config.json"
    f.write_text(json.dumps(config))
    monkeypatch.setenv("DROVA_CONFIG", str(f))

    hosts = load_hosts()
    assert len(hosts) == 2
    assert hosts[0].name == "Зал1-01"
    assert hosts[1].host == "192.168.0.11"
    assert hosts[0].login == "admin"


def test_load_hosts_json_host_overrides_default(monkeypatch, tmp_path):
    config = {
        "defaults": {"login": "admin", "password": "pass"},
        "hosts": [
            {"name": "VIP-01", "host": "192.168.1.10", "login": "vip_admin", "password": "vip_pass"},
        ],
    }
    f = tmp_path / "config.json"
    f.write_text(json.dumps(config))
    monkeypatch.setenv("DROVA_CONFIG", str(f))

    hosts = load_hosts()
    assert hosts[0].login == "vip_admin"
    assert hosts[0].password == "vip_pass"


def test_load_hosts_filter_ips(monkeypatch, tmp_path):
    config = {
        "defaults": {"login": "admin", "password": "pass"},
        "hosts": [
            {"name": "PC-1", "host": "192.168.0.10"},
            {"name": "PC-2", "host": "192.168.0.11"},
            {"name": "PC-3", "host": "192.168.0.12"},
        ],
    }
    f = tmp_path / "config.json"
    f.write_text(json.dumps(config))
    monkeypatch.setenv("DROVA_CONFIG", str(f))

    hosts = load_hosts(filter_ips=["192.168.0.10", "192.168.0.12"])
    assert len(hosts) == 2
    assert {h.host for h in hosts} == {"192.168.0.10", "192.168.0.12"}


# ---------------------------------------------------------------------------
# _build_extra_args
# ---------------------------------------------------------------------------

def test_build_extra_args_empty():
    assert _build_extra_args(_make_args()) == ""


def test_build_extra_args_skip_ffmpeg():
    args = _build_extra_args(_make_args(skip_ffmpeg=True))
    assert "-SkipFFmpeg" in args


def test_build_extra_args_sd_installer():
    args = _build_extra_args(_make_args(sd_installer=r"D:\Setup\SD.exe"))
    assert "-ShadowDefenderInstaller" in args
    assert r"D:\Setup\SD.exe" in args


def test_build_extra_args_sd_password():
    args = _build_extra_args(_make_args(sd_password="secret123"))
    assert "-ShadowDefenderPassword" in args
    assert "secret123" in args


def test_build_extra_args_all_flags():
    args = _build_extra_args(_make_args(
        skip_ffmpeg=True,
        sd_installer=r"D:\SD.exe",
        sd_password="myPwd",
    ))
    assert "-SkipFFmpeg" in args
    assert "-ShadowDefenderInstaller" in args
    assert "-ShadowDefenderPassword" in args
    assert "myPwd" in args


def test_build_extra_args_empty_sd_password_not_included():
    """Empty sd_password should not add -ShadowDefenderPassword to avoid quoting issues."""
    args = _build_extra_args(_make_args(sd_password=""))
    assert "-ShadowDefenderPassword" not in args


# ---------------------------------------------------------------------------
# deploy_one
# ---------------------------------------------------------------------------

_HOST = HostEntry(name="PC-1", host="192.168.0.10", login="admin", password="pass")


def test_deploy_one_success():
    with patch("scripts.deploy._upload_ps1") as mock_upload:
        with patch("scripts.deploy._run_ps1", return_value=(0, "Setup complete!", "")) as mock_run:
            result = deploy_one(_HOST, b"ps1 content", "")

    mock_upload.assert_called_once_with("192.168.0.10", "admin", "pass", b"ps1 content")
    mock_run.assert_called_once_with("192.168.0.10", "admin", "pass", "")
    assert result.success is True
    assert "Setup complete!" in result.output
    assert result.error == ""


def test_deploy_one_nonzero_rc_is_failure():
    with patch("scripts.deploy._upload_ps1"):
        with patch("scripts.deploy._run_ps1", return_value=(1, "fail msg", "stderr")):
            result = deploy_one(_HOST, b"content", "")

    assert result.success is False


def test_deploy_one_upload_exception_skips_run():
    with patch("scripts.deploy._upload_ps1", side_effect=ConnectionError("refused")) as mock_up:
        with patch("scripts.deploy._run_ps1") as mock_run:
            result = deploy_one(_HOST, b"content", "")

    assert result.success is False
    assert "Upload failed" in result.error
    assert "refused" in result.error
    mock_run.assert_not_called()


def test_deploy_one_run_exception():
    with patch("scripts.deploy._upload_ps1"):
        with patch("scripts.deploy._run_ps1", side_effect=TimeoutError("timed out")):
            result = deploy_one(_HOST, b"content", "")

    assert result.success is False
    assert "Execution failed" in result.error
    assert "timed out" in result.error


def test_deploy_one_passes_extra_args_to_run():
    with patch("scripts.deploy._upload_ps1"):
        with patch("scripts.deploy._run_ps1", return_value=(0, "OK", "")) as mock_run:
            deploy_one(_HOST, b"content", "-SkipFFmpeg -ShadowDefenderPassword secret")

    _ip, _login, _pwd, extra = mock_run.call_args[0]
    assert "-SkipFFmpeg" in extra
    assert "secret" in extra


def test_deploy_one_result_fields():
    with patch("scripts.deploy._upload_ps1"):
        with patch("scripts.deploy._run_ps1", return_value=(0, "stdout text", "stderr text")):
            result = deploy_one(_HOST, b"content", "")

    assert result.name == "PC-1"
    assert result.host == "192.168.0.10"
    assert result.output == "stdout text"
    assert result.error == "stderr text"


def test_deploy_one_import_error_if_smbprotocol_missing():
    """If smbprotocol is not installed, upload raises RuntimeError with instructions."""
    with patch.dict("sys.modules", {"smbprotocol.connection": None,
                                     "smbprotocol.session": None,
                                     "smbprotocol.tree": None,
                                     "smbprotocol.open": None}):
        with patch("scripts.deploy._upload_ps1",
                   side_effect=RuntimeError("smbprotocol not installed. Run: poetry install --with setup")):
            result = deploy_one(_HOST, b"content", "")

    assert result.success is False
    assert "smbprotocol not installed" in result.error
