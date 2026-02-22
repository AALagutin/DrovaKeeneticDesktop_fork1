import logging
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import PsExec, ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.drova import SessionsEntity
from drova_desktop_keenetic.common.ffmpeg_stream import OverlayParams, build_ffmpeg_args
from drova_desktop_keenetic.common.geoip import GeoIPClient
from drova_desktop_keenetic.common.host_config import AppConfig, HostConfig
from drova_desktop_keenetic.common.patch import ALL_PATCHES
from drova_desktop_keenetic.common.product_catalog import ProductCatalog

logger = logging.getLogger(__name__)


class BeforeConnect:
    logger = logger.getChild("BeforeConnect")

    def __init__(
        self,
        client: SSHClientConnection,
        host_config: HostConfig,
        session: SessionsEntity | None = None,
        product_catalog: ProductCatalog | None = None,
        geoip_client: GeoIPClient | None = None,
        app_config: AppConfig | None = None,
    ):
        self.client = client
        self.host_config = host_config
        self.session = session
        self.product_catalog = product_catalog
        self.geoip_client = geoip_client
        self.app_config = app_config

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

        await self._start_stream()

        return not failed_patches

    async def _start_stream(self) -> None:
        cfg = self.app_config.streaming if self.app_config else None
        if not cfg or not cfg.enabled:
            return
        if cfg.always_on:
            self.logger.info("Streaming always-on mode — per-session stream start skipped")
            return
        if not self.session or not self.geoip_client:
            self.logger.warning("Streaming enabled but session/geoip_client not provided — skipping")
            return

        self.logger.info("Resolving GeoIP for client %s", self.session.creator_ip)
        geo = await self.geoip_client.lookup(self.session.creator_ip)

        game_title = ""
        if self.product_catalog:
            game_title = self.product_catalog.get_title(self.session.product_id) or ""

        params = OverlayParams(
            pc_ip=self.host_config.host,
            client_ip=str(self.session.creator_ip),
            geo=geo,
            game_title=game_title,
            session_start=self.session.created_on,
        )

        ffmpeg_cmd = build_ffmpeg_args(params, cfg)
        psexec_cmd = str(
            PsExec(
                command=ffmpeg_cmd,
                interactive=1,
                detach=True,
                low_priority=True,
                accepteula=True,
                user=self.host_config.login,
                password=self.host_config.password,
            )
        )

        self.logger.info(
            "Starting FFmpeg stream: rtsp://%s:%d/live/%s",
            cfg.monitor_ip,
            cfg.monitor_port,
            self.host_config.host.replace(".", "-"),
        )
        await self.client.run(psexec_cmd)
