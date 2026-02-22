import logging
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.host_config import HostConfig

logger = logging.getLogger(__name__)


class AfterDisconnect:
    logger = logger.getChild("AfterDisconnect")

    def __init__(
        self,
        client: SSHClientConnection,
        host_config: HostConfig,
        streaming_enabled: bool = False,
        streaming_always_on: bool = False,
    ):
        self.client = client
        self.host_config = host_config
        self.streaming_enabled = streaming_enabled
        self.streaming_always_on = streaming_always_on

    async def run(self) -> bool:
        await sleep(5)

        if self.streaming_enabled and not self.streaming_always_on:
            self.logger.info("Stopping FFmpeg stream")
            await self.client.run(str(TaskKill(image="ffmpeg.exe")))

        self.logger.info("exit from shadow and reboot")
        result = await self.client.run(
            str(
                ShadowDefenderCLI(
                    password=self.host_config.shadow_defender_password,
                    actions=["exit", "reboot"],
                    drives=self.host_config.shadow_defender_drives,
                )
            )
        )
        if result.exit_status:
            # cmdtool.exe is missing or SD service not responding.
            # Fall back to a forced OS reboot; Shadow Defender will discard
            # the shadow data on its own when it detects no valid exit command.
            self.logger.warning(
                f"ShadowDefenderCLI failed (exit_status={result.exit_status}), "
                "cmdtool.exe may have been deleted — falling back to forced reboot"
            )
            await self.client.run("shutdown /r /f /t 0")
        return True
