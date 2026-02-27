import logging
import os
from asyncio import sleep

from asyncssh import SSHClientConnection, SFTPNoSuchFile

from drova_desktop_keenetic.common.commands import PsExec, QWinSta, ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.contants import (
    OBS_PATH,
    OBS_PROFILE,
    OBS_WS_PASSWORD,
    OBS_WS_PORT,
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
)
from drova_desktop_keenetic.common.obs_websocket import OBSWebSocketError, obs_start_recording
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

                # Launch OBS and start recording (optional — only when OBS_PATH is set)
                obs_path = os.environ.get(OBS_PATH)
                if obs_path:
                    await self._launch_obs_and_record(obs_path)

        except Exception:
            self.logger.exception("before_connect: error")

        self.logger.info("before_connect: done")
        return True

    async def _launch_obs_and_record(self, obs_path: str) -> None:
        """Launch obs64.exe in the active session, then connect via WebSocket and start recording."""
        # Detect the active RDP/console session so PsExec -i targets the right desktop
        session_id = 1
        qwinsta = await self.client.run(str(QWinSta()), check=False)
        if not (qwinsta.exit_status or getattr(qwinsta, "returncode", None)):
            stdout = qwinsta.stdout
            if stdout:
                detected = QWinSta.parse_active_session_id(stdout)
                if detected is not None:
                    session_id = detected

        # Build the OBS command line
        obs_cmd = f'"{obs_path}" --minimize-to-tray'
        obs_profile = os.environ.get(OBS_PROFILE)
        if obs_profile:
            obs_cmd += f' --profile "{obs_profile}"'

        self.logger.info("launching OBS in session %d: %s", session_id, obs_cmd)
        launch_result = await self.client.run(
            str(PsExec(command=obs_cmd, interactive=session_id, user="", password="")),
            check=False,
        )
        self.logger.info("OBS launch exit_status=%r stderr=%r", launch_result.exit_status, launch_result.stderr)

        # Connect via OBS WebSocket and start recording.
        # obs_start_recording polls until OBS is ready (handles its startup delay).
        ws_port = int(os.environ.get(OBS_WS_PORT, "4455"))
        ws_password = os.environ.get(OBS_WS_PASSWORD)
        try:
            await obs_start_recording(self.client, ws_port=ws_port, ws_password=ws_password)
            self.logger.info("OBS recording started")
        except OBSWebSocketError as exc:
            self.logger.error("OBS recording failed to start: %s", exc)
