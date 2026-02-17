import logging
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import ShadowDefenderCLI
from drova_desktop_keenetic.common.host_config import HostConfig

logger = logging.getLogger(__name__)


class AfterDisconnect:
    logger = logger.getChild("AfterDisconnect")

    def __init__(self, client: SSHClientConnection, host_config: HostConfig):
        self.client = client
        self.host_config = host_config

    async def run(self) -> bool:
        self.logger.info("exit from shadow and reboot")
        await sleep(5)
        await self.client.run(
            str(
                ShadowDefenderCLI(
                    password=self.host_config.shadow_defender_password,
                    actions=["exit", "reboot"],
                    drives=self.host_config.shadow_defender_drives,
                )
            )
        )
        return True
