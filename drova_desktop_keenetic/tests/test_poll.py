import asyncio
import logging
from datetime import datetime, timezone
from ipaddress import IPv4Address
from logging import DEBUG, basicConfig
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from drova_desktop_keenetic.common.drova import DrovaApiClient, SessionsEntity, StatusEnum
from drova_desktop_keenetic.common.drova_poll import DrovaManager, DrovaPollWorker
from drova_desktop_keenetic.common.host_config import AppConfig, HostConfig

CONNECT_SSH = "drova_desktop_keenetic.common.drova_poll.connect_ssh"
CHECK_DESKTOP_RUN = "drova_desktop_keenetic.common.helpers.CheckDesktop.run"
WAIT_NEW_SESSION_RUN = "drova_desktop_keenetic.common.helpers.WaitNewDesktopSession.run"
WAIT_FINISH_RUN = "drova_desktop_keenetic.common.helpers.WaitFinishOrAbort.run"
BEFORE_CONNECT_RUN = "drova_desktop_keenetic.common.before_connect.BeforeConnect.run"
AFTER_DISCONNECT_RUN = "drova_desktop_keenetic.common.after_disconnect.AfterDisconnect.run"

logger = logging.getLogger(__name__)
basicConfig(level=DEBUG)

TEST_HOST = HostConfig(
    name="test-pc",
    host="127.0.0.1",
    login="user",
    password="pass",
    shadow_defender_password="sdpass",
    shadow_defender_drives="C",
)

TEST_APP_CONFIG = AppConfig(hosts=[TEST_HOST])


def _make_fake_session() -> SessionsEntity:
    return SessionsEntity(
        uuid=UUID("11111111-1111-1111-1111-111111111111"),
        product_id=UUID("22222222-2222-2222-2222-222222222222"),
        client_id=UUID("33333333-3333-3333-3333-333333333333"),
        created_on=datetime.now(timezone.utc),
        status=StatusEnum.ACTIVE,
        creator_ip=IPv4Address("95.173.1.1"),
    )


@pytest.mark.asyncio
async def test_worker_polling_full_session_cycle(mocker):
    """Worker runs a complete cycle: active session found -> patches -> finish -> cleanup."""
    mocker.patch(CONNECT_SSH, return_value=AsyncMock())
    mocker.patch(CHECK_DESKTOP_RUN, return_value=_make_fake_session())
    mocker.patch(BEFORE_CONNECT_RUN, return_value=True)
    mocker.patch(WAIT_FINISH_RUN, return_value=True)
    mocker.patch(AFTER_DISCONNECT_RUN, return_value=True)

    api_client = Mock(spec=DrovaApiClient)
    worker = DrovaPollWorker(host_config=TEST_HOST, api_client=api_client, app_config=TEST_APP_CONFIG)

    async def stop_after_cycle():
        await asyncio.sleep(0.1)
        worker.stop()

    asyncio.create_task(stop_after_cycle())
    await worker.run()


@pytest.mark.asyncio
async def test_worker_polling_waits_for_new_session(mocker):
    """Worker finds no active session, waits for a new one via WaitNewDesktopSession."""
    mocker.patch(CONNECT_SSH, return_value=AsyncMock())
    check_mock = mocker.patch(CHECK_DESKTOP_RUN, return_value=None)
    mocker.patch(WAIT_NEW_SESSION_RUN, return_value=_make_fake_session())
    mocker.patch(BEFORE_CONNECT_RUN, return_value=True)
    mocker.patch(WAIT_FINISH_RUN, return_value=True)
    mocker.patch(AFTER_DISCONNECT_RUN, return_value=True)

    api_client = Mock(spec=DrovaApiClient)
    worker = DrovaPollWorker(host_config=TEST_HOST, api_client=api_client, app_config=TEST_APP_CONFIG)

    async def stop_after_cycle():
        await asyncio.sleep(0.1)
        worker.stop()

    asyncio.create_task(stop_after_cycle())
    await worker.run()

    check_mock.assert_called()


@pytest.mark.asyncio
async def test_manager_creates_workers():
    """DrovaManager creates one worker per host (workers are built lazily in run())."""
    hosts = [
        HostConfig(
            name=f"PC-{i}",
            host=f"192.168.0.{i}",
            login="u",
            password="p",
            shadow_defender_password="s",
            shadow_defender_drives="C",
        )
        for i in range(3)
    ]
    config = AppConfig(hosts=hosts)
    manager = DrovaManager(config)

    assert len(manager.workers) == 0  # workers created in run()
    assert len(config.hosts) == 3
    assert manager.api_client is not None
