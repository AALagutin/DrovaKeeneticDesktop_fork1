import asyncio
import logging
import os
from logging import DEBUG, basicConfig

from asyncssh import connect as connect_ssh
from asyncssh.misc import ChannelOpenError

from drova_desktop_keenetic.common.after_disconnect import AfterDisconnect
from drova_desktop_keenetic.common.before_connect import BeforeConnect
from drova_desktop_keenetic.common.contants import (
    WINDOWS_HOST,
    WINDOWS_LOGIN,
    WINDOWS_PASSWORD,
)
from drova_desktop_keenetic.common.drova import get_new_session
from drova_desktop_keenetic.common.gamepc_diagnostic import GamePCDiagnostic
from drova_desktop_keenetic.common.helpers import (
    CheckDesktop,
    RebootRequired,
    WaitFinishOrAbort,
    WaitNewDesktopSession,
)

logger = logging.getLogger(__name__)


class DrovaPoll:
    def __init__(
        self,
        windows_host: str = os.environ[WINDOWS_HOST],
        windows_login: str = os.environ[WINDOWS_LOGIN],
        windows_password: str = os.environ[WINDOWS_PASSWORD],
    ):
        self.windows_host = windows_host
        self.windows_login = windows_login
        self.windows_password = windows_password

        self.stop_future = asyncio.get_event_loop().create_future()

    async def polling(self) -> None:
        while not self.stop_future.done():
            try:
                async with connect_ssh(
                    host=self.windows_host,
                    username=self.windows_login,
                    password=self.windows_password,
                    known_hosts=None,
                    encoding="windows-1251",
                ) as conn:
                    try:
                        check = CheckDesktop(conn)
                        is_desktop_session = await check.run()

                        if not is_desktop_session:
                            is_desktop_session = await WaitNewDesktopSession(conn).run()

                        if is_desktop_session:
                            logger.info("poll: session active — starting setup")
                            await BeforeConnect(conn).run()

                            logger.info("poll: waiting for session end")
                            await WaitFinishOrAbort(conn).run()

                            logger.info("poll: session ended — running cleanup")
                            await AfterDisconnect(conn).run()
                    except RebootRequired:
                        logger.warning("poll: reboot required — running cleanup")
                        await AfterDisconnect(conn).run()

            except (ChannelOpenError, OSError):
                logger.debug("poll: ssh unreachable")
            except:
                logger.exception("poll: unexpected error")

            await asyncio.sleep(1)

    async def stop(self) -> None:
        self.stop_future.set_result(True)

    async def _waitif_session_desktop_exists(self) -> None:
        try:
            async with connect_ssh(
                host=self.windows_host,
                username=self.windows_login,
                password=self.windows_password,
                known_hosts=None,
                encoding="windows-1251",
            ) as conn:
                try:
                    if await CheckDesktop(conn).run():
                        logger.info("poll: existing session — waiting for end")
                        await WaitFinishOrAbort(conn).run()

                        logger.info("poll: session ended — running cleanup")
                        await AfterDisconnect(conn).run()
                except RebootRequired:
                    logger.warning("poll: reboot required — running cleanup")
                    await AfterDisconnect(conn).run()
        except:
            logger.exception("poll: startup check error")

    async def _run_startup_diagnostic(self) -> None:
        try:
            async with connect_ssh(
                host=self.windows_host,
                username=self.windows_login,
                password=self.windows_password,
                known_hosts=None,
                encoding="windows-1251",
            ) as conn:
                await GamePCDiagnostic(conn, self.windows_host).run()
        except (ChannelOpenError, OSError):
            logger.warning("diagnostic: host unreachable (rebooting?)")
        except Exception:
            logger.exception("diagnostic: unexpected error")

    async def serve(self, wait_forever=False):
        logger.info("worker: start host=%s", self.windows_host)
        await self._run_startup_diagnostic()
        await self._waitif_session_desktop_exists()

        if wait_forever:
            await self.polling()
        else:
            asyncio.create_task(self.polling())
