import logging
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.host_config import HostConfig
from drova_desktop_keenetic.common.patch import ALL_PATCHES

logger = logging.getLogger(__name__)


class BeforeConnect:
    logger = logger.getChild("BeforeConnect")

    def __init__(self, client: SSHClientConnection, host_config: HostConfig):
        self.client = client
        self.host_config = host_config

    async def run(self) -> bool:
        self.logger.info("open sftp")
        async with self.client.start_sftp_client() as sftp:

            self.logger.info("start shadow")
            await self.client.run(
                str(
                    ShadowDefenderCLI(
                        password=self.host_config.shadow_defender_password,
                        actions=["enter"],
                        drives=self.host_config.shadow_defender_drives,
                    )
                )
            )
            await sleep(2)

            # Pre-schedule SD exit on next reboot as a safety net.
            # If cmdtool.exe gets deleted during the session, AfterDisconnect
            # will fall back to a forced OS reboot. Because this exit flag was
            # already set while cmdtool was still alive, that reboot will still
            # properly exit Shadow Defender mode.
            self.logger.info("pre-schedule shadow exit on next reboot (safety net)")
            await self.client.run(
                str(
                    ShadowDefenderCLI(
                        password=self.host_config.shadow_defender_password,
                        actions=["exit"],
                        drives=self.host_config.shadow_defender_drives,
                    )
                )
            )

            failed_patches: list[str] = []
            for patch_cls in ALL_PATCHES:
                self.logger.info(f"prepare {patch_cls.NAME}")
                if patch_cls.TASKKILL_IMAGE:
                    await self.client.run(str(TaskKill(image=patch_cls.TASKKILL_IMAGE)))
                await sleep(0.2)
                patcher = patch_cls(self.client, sftp)
                try:
                    await patcher.patch()
                except Exception:
                    self.logger.exception(f"Patch failed: {patch_cls.NAME}")
                    failed_patches.append(patch_cls.NAME)

        if failed_patches:
            self.logger.error(f"Failed patches: {failed_patches}")
            return False
        return True
