import asyncio
import logging
from pathlib import Path

from asyncssh import connect as connect_ssh
from asyncssh.misc import ChannelOpenError
from expiringdict import ExpiringDict  # type: ignore

from drova_desktop_keenetic.common.after_disconnect import AfterDisconnect
from drova_desktop_keenetic.common.before_connect import BeforeConnect
from drova_desktop_keenetic.common.cleanup_restrictions import CleanupRestrictions
from drova_desktop_keenetic.common.commands import PsExec
from drova_desktop_keenetic.common.drova import DrovaApiClient
from drova_desktop_keenetic.common.ffmpeg_stream import build_ffmpeg_args_idle
from drova_desktop_keenetic.common.geoip import GeoIPClient
from drova_desktop_keenetic.common.helpers import (
    CheckDesktop,
    RebootRequired,
    WaitFinishOrAbort,
    WaitNewDesktopSession,
)
from drova_desktop_keenetic.common.host_config import AppConfig, HostConfig
from drova_desktop_keenetic.common.product_catalog import ProductCatalog

logger = logging.getLogger(__name__)


class DrovaPollWorker:
    """Manages the session lifecycle for a single Windows PC."""

    def __init__(
        self,
        host_config: HostConfig,
        api_client: DrovaApiClient,
        app_config: AppConfig,
        poll_interval_idle: float = 5.0,
        poll_interval_active: float = 3.0,
        product_catalog: ProductCatalog | None = None,
        geoip_client: GeoIPClient | None = None,
    ):
        self.host_config = host_config
        self.api_client = api_client
        self.app_config = app_config
        self.poll_interval_idle = poll_interval_idle
        self.poll_interval_active = poll_interval_active
        self.product_catalog = product_catalog
        self.geoip_client = geoip_client
        self.token_cache = ExpiringDict(max_len=10, max_age_seconds=600)
        self._stop_event = asyncio.Event()
        self.logger = logger.getChild(f"Worker[{host_config.name}]")

    def _connect_ssh(self):
        return connect_ssh(
            host=self.host_config.host,
            username=self.host_config.login,
            password=self.host_config.password,
            known_hosts=None,
            encoding="windows-1251",
        )

    @property
    def _streaming_enabled(self) -> bool:
        return self.app_config.streaming.enabled

    @property
    def _streaming_always_on(self) -> bool:
        return self.app_config.streaming.enabled and self.app_config.streaming.always_on

    async def _start_idle_stream(self, conn) -> None:
        """Start FFmpeg in always-on mode (no active session context needed)."""
        cfg = self.app_config.streaming
        ffmpeg_cmd = build_ffmpeg_args_idle(self.host_config.host, cfg)
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
            "Starting idle FFmpeg stream (always-on): rtsp://%s:%d/live/%s",
            cfg.monitor_ip,
            cfg.monitor_port,
            self.host_config.host.replace(".", "-"),
        )
        await conn.run(psexec_cmd)

    async def _handle_session(self, conn, token_cache: ExpiringDict) -> None:
        """Handle one complete session cycle: check -> wait -> prepare -> wait_finish -> cleanup."""
        check = CheckDesktop(conn, self.api_client, token_cache, product_catalog=self.product_catalog)
        session = await check.run()

        if session is None:
            await self._maybe_cleanup_restrictions(conn)
            wait_new = WaitNewDesktopSession(
                conn, self.api_client, token_cache,
                poll_interval=self.poll_interval_idle, product_catalog=self.product_catalog,
            )
            session = await wait_new.run()

        self.logger.info("Desktop session detected - applying patches")
        before_connect = BeforeConnect(
            conn,
            self.host_config,
            session=session,
            product_catalog=self.product_catalog,
            geoip_client=self.geoip_client,
            app_config=self.app_config,
        )
        patches_ok = await before_connect.run()
        if not patches_ok:
            self.logger.warning("Some patches failed, but continuing with session")

        self.logger.info("Waiting for session to finish")
        wait_finish = WaitFinishOrAbort(
            conn, self.api_client, token_cache,
            poll_interval=self.poll_interval_active, product_catalog=self.product_catalog,
        )
        await wait_finish.run()

        self.logger.info("Session finished - exiting shadow defender and rebooting")
        after = AfterDisconnect(
            conn, self.host_config,
            streaming_enabled=self._streaming_enabled,
        )
        await after.run()

    async def _maybe_cleanup_restrictions(self, conn) -> None:
        """If restrictions from a previous interrupted session are still active, remove them."""
        cleanup = CleanupRestrictions(conn)
        try:
            if await cleanup.is_stuck():
                self.logger.warning(
                    "Stuck restrictions detected (no active session) — cleaning up"
                )
                await cleanup.run()
        except Exception:
            self.logger.exception("Failed to clean up stuck restrictions")

    async def polling(self) -> None:
        self.logger.info("Started polling")
        while not self._stop_event.is_set():
            try:
                async with self._connect_ssh() as conn:
                    if self._streaming_always_on:
                        await self._start_idle_stream(conn)
                    try:
                        await self._handle_session(conn, self.token_cache)
                    except RebootRequired:
                        self.logger.info("Reboot required")
                        after = AfterDisconnect(
                            conn, self.host_config,
                            streaming_enabled=self._streaming_enabled,
                        )
                        await after.run()
            except (ChannelOpenError, OSError):
                self.logger.debug("Cannot connect - PC unavailable or rebooting")
            except Exception:
                self.logger.exception("Unexpected error in polling cycle")

            await asyncio.sleep(1)

    async def run(self) -> None:
        """Entry point: check for existing session, then start polling."""
        await self._check_existing_session()
        await self.polling()

    async def _check_existing_session(self) -> None:
        """On startup, check if a session is already active and handle it."""
        try:
            async with self._connect_ssh() as conn:
                try:
                    check = CheckDesktop(conn, self.api_client, self.token_cache, product_catalog=self.product_catalog)
                    session = await check.run()
                    if session is not None:
                        self.logger.info("Existing session found - waiting for it to finish")
                        wait_finish = WaitFinishOrAbort(
                            conn, self.api_client, self.token_cache,
                            poll_interval=self.poll_interval_active, product_catalog=self.product_catalog,
                        )
                        await wait_finish.run()

                        self.logger.info("Session finished - cleanup")
                        after = AfterDisconnect(
                            conn, self.host_config,
                            streaming_enabled=self._streaming_enabled,
                        )
                        await after.run()
                except RebootRequired:
                    self.logger.info("Reboot required on startup check")
                    after = AfterDisconnect(
                        conn, self.host_config,
                        streaming_enabled=self._streaming_enabled,
                    )
                    await after.run()
        except (ChannelOpenError, OSError):
            self.logger.debug("Cannot connect on startup - PC unavailable or rebooting")
        except Exception:
            self.logger.exception("Error checking existing session on startup")

    def stop(self):
        self._stop_event.set()


class DrovaManager:
    """Manages multiple DrovaPollWorker instances in a single process."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.api_client = DrovaApiClient()
        self.product_catalog = ProductCatalog(config.product_catalog_path)
        self.geoip_client: GeoIPClient | None = None
        self.workers: list[DrovaPollWorker] = []

    async def run(self) -> None:
        logger.info(f"Starting DrovaManager with {len(self.config.hosts)} host(s)")

        # Refresh product catalog if needed (once per day)
        if self.product_catalog.needs_refresh():
            logger.info("Product catalog needs refresh, fetching from API...")
            await self.product_catalog.refresh(self.api_client)
        else:
            logger.info(f"Product catalog is up to date ({self.product_catalog.product_count} products)")

        # Initialise GeoIP client when streaming is enabled
        if self.config.streaming.enabled:
            self.geoip_client = GeoIPClient(
                db_dir=Path(self.config.streaming.geoip_db_dir),
                update_interval_days=self.config.streaming.geoip_update_interval_days,
            )
            logger.info("Initialising GeoIP databases…")
            await self.geoip_client.initialize()

        for host_config in self.config.hosts:
            worker = DrovaPollWorker(
                host_config=host_config,
                api_client=self.api_client,
                app_config=self.config,
                poll_interval_idle=self.config.poll_interval_idle,
                poll_interval_active=self.config.poll_interval_active,
                product_catalog=self.product_catalog,
                geoip_client=self.geoip_client,
            )
            self.workers.append(worker)

        tasks = [asyncio.create_task(w.run(), name=w.host_config.name) for w in self.workers]

        # Background GeoIP database refresh
        if self.geoip_client:
            tasks.append(asyncio.create_task(self.geoip_client.update_loop(), name="geoip-update"))

        try:
            await asyncio.gather(*tasks)
        finally:
            await self.api_client.close()
            if self.geoip_client:
                await self.geoip_client.close()

    async def stop(self) -> None:
        for worker in self.workers:
            worker.stop()
        await self.api_client.close()
        if self.geoip_client:
            await self.geoip_client.close()
