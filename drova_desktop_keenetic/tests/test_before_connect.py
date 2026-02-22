"""Tests for BeforeConnect: SD/ffmpeg ordering and failure logging."""

import logging
from datetime import datetime, timezone
from ipaddress import IPv4Address
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from drova_desktop_keenetic.common.before_connect import BeforeConnect
from drova_desktop_keenetic.common.drova import SessionsEntity, StatusEnum
from drova_desktop_keenetic.common.geoip import GeoIPInfo
from drova_desktop_keenetic.common.host_config import AppConfig, HostConfig, StreamingConfig

_MODULE = "drova_desktop_keenetic.common.before_connect"

_HOST = HostConfig(
    name="test-pc",
    host="127.0.0.1",
    login="user",
    password="pass",
    shadow_defender_password="sdpass",
    shadow_defender_drives="C",
)


def _app(always_on: bool = False) -> AppConfig:
    return AppConfig(
        hosts=[_HOST],
        streaming=StreamingConfig(enabled=True, monitor_ip="192.168.1.200", always_on=always_on),
    )


def _session() -> SessionsEntity:
    return SessionsEntity(
        uuid=UUID("11111111-1111-1111-1111-111111111111"),
        product_id=UUID("22222222-2222-2222-2222-222222222222"),
        client_id=UUID("33333333-3333-3333-3333-333333333333"),
        created_on=datetime.now(timezone.utc),
        status=StatusEnum.ACTIVE,
        creator_ip=IPv4Address("95.173.1.1"),
    )


def _ok() -> MagicMock:
    return MagicMock(exit_status=0, stderr=b"")


def _fail() -> MagicMock:
    return MagicMock(exit_status=1, stderr=b"error detail")


def _make_client() -> AsyncMock:
    """SSH client mock whose run() returns success by default.

    start_sftp_client() must be a plain MagicMock (not AsyncMock) so that
    calling it returns an AsyncMock directly — not a coroutine — allowing
    ``async with client.start_sftp_client() as sftp:`` to work correctly.
    """
    client = AsyncMock()
    client.run.return_value = _ok()
    client.start_sftp_client = MagicMock(return_value=AsyncMock())
    return client


def _call_cmds(client: AsyncMock) -> list[str]:
    """Return all command strings passed to client.run(), lower-cased."""
    return [c.args[0].lower() for c in client.run.call_args_list if c.args]


# ---------------------------------------------------------------------------
# Ordering: idle kill must come before SD enter when always_on=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_always_on_idle_kill_before_sd_enter():
    """TaskKill(ffmpeg.exe) must be issued BEFORE ShadowDefenderCLI enter."""
    client = _make_client()
    bc = BeforeConnect(client=client, host_config=_HOST, app_config=_app(always_on=True))

    with patch(f"{_MODULE}.ALL_PATCHES", []), \
         patch(f"{_MODULE}.sleep", AsyncMock()), \
         patch.object(BeforeConnect, "_start_stream", AsyncMock()):
        await bc.run()

    cmds = _call_cmds(client)
    kill_idx = next((i for i, c in enumerate(cmds) if "taskkill" in c), None)
    sd_idx = next((i for i, c in enumerate(cmds) if "cmdtool" in c), None)

    assert kill_idx is not None, "TaskKill was never called"
    assert sd_idx is not None, "ShadowDefenderCLI enter was never called"
    assert kill_idx < sd_idx, (
        f"TaskKill (call #{kill_idx}) must come BEFORE SD enter (call #{sd_idx})"
    )


@pytest.mark.asyncio
async def test_not_always_on_no_early_taskkill():
    """When always_on=False, the first client.run() call must be SD enter, not TaskKill."""
    client = _make_client()
    bc = BeforeConnect(client=client, host_config=_HOST, app_config=_app(always_on=False))

    with patch(f"{_MODULE}.ALL_PATCHES", []), \
         patch(f"{_MODULE}.sleep", AsyncMock()), \
         patch.object(BeforeConnect, "_start_stream", AsyncMock()):
        await bc.run()

    cmds = _call_cmds(client)
    assert cmds, "No calls to client.run()"
    assert "taskkill" not in cmds[0], "No early TaskKill expected when always_on=False"
    assert "cmdtool" in cmds[0], "First call must be Shadow Defender enter"


# ---------------------------------------------------------------------------
# SD enter result handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sd_enter_failure_is_logged(caplog):
    """exit_status != 0 from SD enter must produce an ERROR log entry."""
    client = _make_client()
    # With always_on=False the first run() call is SD enter — make it fail
    client.run.side_effect = [_fail()] + [_ok()] * 20

    bc = BeforeConnect(client=client, host_config=_HOST, app_config=_app(always_on=False))

    with patch(f"{_MODULE}.ALL_PATCHES", []), \
         patch(f"{_MODULE}.sleep", AsyncMock()), \
         patch.object(BeforeConnect, "_start_stream", AsyncMock()), \
         caplog.at_level(logging.ERROR):
        await bc.run()

    assert any(
        "FAILED" in r.message and r.levelno == logging.ERROR
        for r in caplog.records
    ), f"Expected ERROR about SD failure; got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_sd_enter_success_no_sd_error_logged(caplog):
    """Successful SD enter must not produce any Shadow Defender ERROR log."""
    client = _make_client()
    bc = BeforeConnect(client=client, host_config=_HOST, app_config=_app(always_on=False))

    with patch(f"{_MODULE}.ALL_PATCHES", []), \
         patch(f"{_MODULE}.sleep", AsyncMock()), \
         patch.object(BeforeConnect, "_start_stream", AsyncMock()), \
         caplog.at_level(logging.ERROR):
        await bc.run()

    sd_errors = [
        r for r in caplog.records
        if r.levelno == logging.ERROR and "shadow defender" in r.message.lower()
    ]
    assert not sd_errors, f"Unexpected SD error logs: {[r.message for r in sd_errors]}"


# ---------------------------------------------------------------------------
# _start_stream: PsExec failure logging
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_stream_psexec_failure_logged(caplog):
    """PsExec exit_status != 0 when launching session FFmpeg must emit ERROR."""
    # Selectively fail only the psexec call
    async def selective_run(cmd):
        if "psexec" in cmd.lower():
            return _fail()
        return _ok()

    client = AsyncMock()
    client.run.side_effect = selective_run
    client.start_sftp_client = MagicMock(return_value=AsyncMock())

    geo_mock = AsyncMock()
    geo_mock.lookup.return_value = GeoIPInfo(city="Moscow", isp="ISP", asn="AS123")

    bc = BeforeConnect(
        client=client,
        host_config=_HOST,
        app_config=_app(always_on=True),
        session=_session(),
        geoip_client=geo_mock,
    )

    with patch(f"{_MODULE}.ALL_PATCHES", []), \
         patch(f"{_MODULE}.sleep", AsyncMock()), \
         caplog.at_level(logging.ERROR):
        await bc.run()

    assert any(
        "PsExec" in r.message and r.levelno == logging.ERROR
        for r in caplog.records
    ), f"Expected PsExec ERROR; got: {[r.message for r in caplog.records]}"
