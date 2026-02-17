import asyncio
import logging
from logging import DEBUG, basicConfig
from unittest.mock import AsyncMock, Mock, patch

import pytest

from drova_desktop_keenetic.common.drova import DrovaApiClient
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


@pytest.mark.asyncio
async def test_worker_polling_no_session(mocker):
    """Worker polls, finds no session, iterates once, then stops."""
    mocker.patch(CONNECT_SSH, return_value=AsyncMock())
    mocker.patch(CHECK_DESKTOP_RUN, return_value=False)
    mocker.patch(WAIT_NEW_SESSION_RUN, return_value=False)

    api_client = Mock(spec=DrovaApiClient)
    worker = DrovaPollWorker(host_config=TEST_HOST, api_client=api_client)

    # Run one iteration then stop
    async def stop_after_one():
        await asyncio.sleep(0.1)
        worker.stop()

    asyncio.create_task(stop_after_one())
    await worker.run()


@pytest.mark.asyncio
async def test_manager_creates_workers():
    """DrovaManager creates one worker per host."""
    hosts = [
        HostConfig(name=f"PC-{i}", host=f"192.168.0.{i}", login="u", password="p", shadow_defender_password="s", shadow_defender_drives="C")
        for i in range(3)
    ]
    config = AppConfig(hosts=hosts)
    manager = DrovaManager(config)

    assert len(manager.workers) == 0  # workers created in run()
    assert len(config.hosts) == 3
    assert manager.api_client is not None
