import asyncio
import logging
import os

from asyncssh import connect as connect_ssh

from drova_desktop_keenetic.common.after_disconnect import AfterDisconnect
from drova_desktop_keenetic.common.before_connect import BeforeConnect
from drova_desktop_keenetic.common.contants import (
    DROVA_SOCKET_LISTEN,
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
    WINDOWS_HOST,
    WINDOWS_LOGIN,
    WINDOWS_PASSWORD,
)
from drova_desktop_keenetic.common.drova import DrovaApiClient
from drova_desktop_keenetic.common.drova_server_binary import (
    DrovaBinaryProtocol,
    Socket,
)
from drova_desktop_keenetic.common.helpers import CheckDesktop, WaitFinishOrAbort
from drova_desktop_keenetic.common.host_config import HostConfig

logger = logging.getLogger(__name__)


class DrovaSocket:
    def __init__(
        self,
        drova_socket_listen: int | None = None,
        windows_host: str | None = None,
        windows_login: str | None = None,
        windows_password: str | None = None,
    ):
        drova_socket_listen = drova_socket_listen if drova_socket_listen is not None else int(os.environ.get(DROVA_SOCKET_LISTEN, "0"))
        windows_host = windows_host or os.environ[WINDOWS_HOST]
        windows_login = windows_login or os.environ[WINDOWS_LOGIN]
        windows_password = windows_password or os.environ[WINDOWS_PASSWORD]
        self.drova_socket_listen = drova_socket_listen
        self.windows_host = windows_host
        self.windows_login = windows_login
        self.windows_password = windows_password

        self.server: asyncio.Server | None = None
        self.api_client = DrovaApiClient()
        self._host_config = HostConfig(
            name="default",
            host=windows_host,
            login=windows_login,
            password=windows_password,
            shadow_defender_password=os.environ.get(SHADOW_DEFENDER_PASSWORD, ""),
            shadow_defender_drives=os.environ.get(SHADOW_DEFENDER_DRIVES, ""),
        )

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        await self.api_client.close()

    async def server_accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        logger.debug(f"Accept! to {self.windows_host}:7985")

        target_socket = await asyncio.open_connection(self.windows_host, 7985)
        drova_pass = DrovaBinaryProtocol(Socket(reader, writer), Socket(*target_socket))
        logger.info("Wait drova windows-server answer")
        if await drova_pass.wait_server_answered():
            logger.info("Server answered - connect and prepare windows host")
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
            check_desktop = CheckDesktop(conn, self.api_client)
            is_desktop = await check_desktop.run()
            logger.info(f"Session is Desktop! -> {is_desktop}")

            if is_desktop:
                logger.info("Start beforeConnect")
                before_connect = BeforeConnect(conn, self._host_config)
                await before_connect.run()

                logger.info("Wait finish session")
                wait_finish_session = WaitFinishOrAbort(conn, self.api_client)
                await wait_finish_session.run()

                logger.info("Clear shadow defender and restart")
                after_disconnect_client = AfterDisconnect(conn, self._host_config)
                await after_disconnect_client.run()

    async def _waitif_session_desktop_exists(self):
        async with connect_ssh(
            host=self.windows_host,
            username=self.windows_login,
            password=self.windows_password,
            known_hosts=None,
            encoding="windows-1251",
        ) as conn:
            check_desktop = CheckDesktop(conn, self.api_client)
            is_desktop = await check_desktop.run()
            if is_desktop:
                logger.info("Wait finish session")
                wait_finish_session = WaitFinishOrAbort(conn, self.api_client)
                await wait_finish_session.run()

                logger.info("Clear shadow defender and restart")
                after_disconnect_client = AfterDisconnect(conn, self._host_config)
                await after_disconnect_client.run()

    async def serve(self, wait_forever=False):
        await self._waitif_session_desktop_exists()

        self.server = await asyncio.start_server(self.server_accept, "0.0.0.0", self.drova_socket_listen, limit=1)

        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        logger.info(f"Serving on {addrs}")

        if not wait_forever:
            await self.server.start_serving()
        else:
            await self.server.serve_forever()
