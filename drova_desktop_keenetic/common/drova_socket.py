import asyncio
import logging
import os
from logging import DEBUG, basicConfig

from asyncssh import connect as connect_ssh

from drova_desktop_keenetic.common.after_disconnect import AfterDisconnect
from drova_desktop_keenetic.common.before_connect import BeforeConnect
from drova_desktop_keenetic.common.contants import (
    DROVA_SOCKET_LISTEN,
    WINDOWS_HOST,
    WINDOWS_LOGIN,
    WINDOWS_PASSWORD,
)
from drova_desktop_keenetic.common.drova_server_binary import (
    DrovaBinaryProtocol,
    Socket,
)
from drova_desktop_keenetic.common.helpers import CheckDesktop, WaitFinishOrAbort

logger = logging.getLogger(__name__)


class DrovaSocket:
    def __init__(
        self,
        drova_socket_listen: int | None = None,
        windows_host: str | None = None,
        windows_login: str | None = None,
        windows_password: str | None = None,
    ):
        self.drova_socket_listen = drova_socket_listen if drova_socket_listen is not None else int(os.environ.get(DROVA_SOCKET_LISTEN, 0))
        self.windows_host = windows_host if windows_host is not None else os.environ[WINDOWS_HOST]
        self.windows_login = windows_login if windows_login is not None else os.environ[WINDOWS_LOGIN]
        self.windows_password = windows_password if windows_password is not None else os.environ[WINDOWS_PASSWORD]

        self.server: asyncio.Server | None = None

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def server_accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        logger.debug("socket: accept %s:7985", self.windows_host)

        target_socket = await asyncio.open_connection(self.windows_host, 7985)
        drova_pass = DrovaBinaryProtocol(Socket(reader, writer), Socket(*target_socket))
        logger.info("socket: awaiting server ack")
        if await drova_pass.wait_server_answered():
            logger.info("socket: server acked — starting session flow")
            await self._run_server_acked()
        else:
            await drova_pass.clear()

    async def _run_server_acked(self):
        async with connect_ssh(
            host=self.windows_host,
            username=self.windows_login,
            password=self.windows_password,
            known_hosts=None,
            encoding="windows-1251",
        ) as conn:
            is_desktop = await CheckDesktop(conn).run()

            if is_desktop:
                logger.info("socket: session active — starting setup")
                await BeforeConnect(conn).run()

                logger.info("socket: waiting for session end")
                await WaitFinishOrAbort(conn).run()

                logger.info("socket: session ended — running cleanup")
                await AfterDisconnect(conn).run()

    async def _waitif_session_desktop_exists(self):
        async with connect_ssh(
            host=self.windows_host,
            username=self.windows_login,
            password=self.windows_password,
            known_hosts=None,
            encoding="windows-1251",
        ) as conn:
            if await CheckDesktop(conn).run():
                logger.info("socket: existing session — waiting for end")
                await WaitFinishOrAbort(conn).run()

                logger.info("socket: session ended — running cleanup")
                await AfterDisconnect(conn).run()

    async def serve(self, wait_forever=False):
        await self._waitif_session_desktop_exists()

        self.server = await asyncio.start_server(self.server_accept, "0.0.0.0", self.drova_socket_listen, limit=1)

        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        logger.info("socket: serving on %s", addrs)

        if not wait_forever:
            await self.server.start_serving()
        else:
            await self.server.serve_forever()
