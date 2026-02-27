import logging
import os
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import ShadowDefenderCLI
from drova_desktop_keenetic.common.contants import (
    OBS_PATH,
    OBS_WS_PASSWORD,
    OBS_WS_PORT,
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
)
from drova_desktop_keenetic.common.obs_websocket import obs_stop_recording

logger = logging.getLogger(__name__)


class AfterDisconnect:
    logger = logger.getChild("AfterDisconnect")

    def __init__(self, client: SSHClientConnection):
        self.client = client

    async def run(self) -> bool:
        self.logger.info("after_disconnect: start")

        # Stop OBS recording before Shadow Defender rolls back the disk.
        # obs_stop_recording never raises — a failed stop won't prevent the reboot.
        if os.environ.get(OBS_PATH):
            ws_port = int(os.environ.get(OBS_WS_PORT, "4455"))
            ws_password = os.environ.get(OBS_WS_PASSWORD)
            output_path = await obs_stop_recording(self.client, ws_port=ws_port, ws_password=ws_password)
            if output_path:
                self.logger.info("after_disconnect: recording saved to %s", output_path)

        self.logger.info("after_disconnect: SD exit+reboot")
        await sleep(5)
        await self.client.run(
            str(
                ShadowDefenderCLI(
                    password=os.environ[SHADOW_DEFENDER_PASSWORD],
                    actions=["exit", "reboot"],
                    drives=os.environ[SHADOW_DEFENDER_DRIVES],
                )
            )
        )

        return True
