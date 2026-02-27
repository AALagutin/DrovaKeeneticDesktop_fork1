import logging
import os
from asyncio import sleep

from asyncssh import SSHClientConnection, SFTPNoSuchFile

from drova_desktop_keenetic.common.commands import ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.contants import (
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
)
from drova_desktop_keenetic.common.patch import ALL_PATCHES

logger = logging.getLogger(__name__)


class BeforeConnect:
    logger = logger.getChild("BeforeConnect")

    def __init__(self, client: SSHClientConnection):
        self.client = client

    async def run(self) -> bool:
        self.logger.info("before_connect: start")
        try:
            async with self.client.start_sftp_client() as sftp:
                await self.client.run(
                    str(
                        ShadowDefenderCLI(
                            password=os.environ[SHADOW_DEFENDER_PASSWORD],
                            actions=["enter"],
                            drives=os.environ[SHADOW_DEFENDER_DRIVES],
                        )
                    )
                )
                await sleep(2)

                for path in ALL_PATCHES:
                    if path.TASKKILL_IMAGE:
                        await self.client.run(str(TaskKill(image=path.TASKKILL_IMAGE)))
                    await sleep(0.2)
                    try:
                        await path(self.client, sftp).patch()
                    except SFTPNoSuchFile as e:
                        self.logger.warning("patch %s: file not found on remote — skipped: %s", path.NAME, e)
                    except Exception:
                        self.logger.warning("patch %s: FAILED — skipped", path.NAME, exc_info=True)

        except Exception:
            self.logger.exception("before_connect: error")

        self.logger.info("before_connect: done")
        return True
