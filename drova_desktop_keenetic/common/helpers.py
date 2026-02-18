import logging
from asyncio import sleep

from asyncssh import SSHClientConnection
from expiringdict import ExpiringDict  # type: ignore

from drova_desktop_keenetic.common.commands import NotFoundAuthCode, RegQueryEsme
from drova_desktop_keenetic.common.drova import (
    UUID_DESKTOP,
    DrovaApiClient,
    SessionsEntity,
    StatusEnum,
)

logger = logging.getLogger(__name__)


class RebootRequired(RuntimeError): ...


class BaseDrovaMerchantWindows:
    logger = logger.getChild("BaseDrovaMerchantWindows")

    def __init__(
        self,
        client: SSHClientConnection,
        api_client: DrovaApiClient | None = None,
        token_cache: ExpiringDict | None = None,
    ):
        self.client = client
        self.api_client = api_client or DrovaApiClient()
        self.dict_store = token_cache if token_cache is not None else ExpiringDict(max_len=100, max_age_seconds=60)

    async def get_servers(self) -> list[tuple[str, str]]:
        if "servers" not in self.dict_store:
            await self.refresh_actual_tokens()
        return self.dict_store["servers"]

    async def get_auth_token(self) -> str:
        if "auth_token" not in self.dict_store:
            servers = await self.get_servers()
            self.dict_store["server_id"] = servers[0][0]
            self.dict_store["auth_token"] = servers[0][1]
        return self.dict_store["auth_token"]

    async def get_server_id(self) -> str:
        if "server_id" not in self.dict_store:
            servers = await self.get_servers()
            self.dict_store["server_id"] = servers[0][0]
            self.dict_store["auth_token"] = servers[0][1]
        return self.dict_store["server_id"]

    def set_active_server(self, server_id: str, auth_token: str) -> None:
        self.dict_store["server_id"] = server_id
        self.dict_store["auth_token"] = auth_token

    async def refresh_actual_tokens(self) -> list[tuple[str, str]]:
        complete_process = await self.client.run(str(RegQueryEsme()))
        stdout = b""

        if complete_process.exit_status or complete_process.returncode:
            raise RebootRequired()

        try:
            if isinstance(complete_process.stdout, str):
                stdout = complete_process.stdout.encode()
            servers = RegQueryEsme.parseAuthCode(stdout=stdout)
        except NotFoundAuthCode:
            raise RebootRequired
        self.dict_store["servers"] = servers
        return servers

    async def check_desktop_session(self, session: SessionsEntity, auth_token: str | None = None) -> bool:
        if session.product_id == UUID_DESKTOP:
            return True
        cache_key = f"product:{session.product_id}"
        if cache_key in self.dict_store:
            return self.dict_store[cache_key]
        token = auth_token or await self.get_auth_token()
        product_info = await self.api_client.get_product_info(session.product_id, auth_token=token)
        self.logger.info(f"Product '{product_info.title}' use_default_desktop={product_info.use_default_desktop}")
        self.dict_store[cache_key] = product_info.use_default_desktop
        return product_info.use_default_desktop


class CheckDesktop(BaseDrovaMerchantWindows):
    logger = logger.getChild("CheckDesktop")

    async def run(self) -> bool:
        self.logger.info("Checking for active desktop session")
        servers = await self.get_servers()
        for server_id, auth_token in servers:
            session = await self.api_client.get_latest_session(server_id, auth_token)
            self.logger.debug(f"Server {server_id}: session={session}")

            if not session:
                continue

            if session.status in (StatusEnum.HANDSHAKE, StatusEnum.ACTIVE, StatusEnum.NEW):
                if await self.check_desktop_session(session, auth_token):
                    self.set_active_server(server_id, auth_token)
                    return True
        return False


class WaitFinishOrAbort(BaseDrovaMerchantWindows):
    logger = logger.getChild("WaitFinishOrAbort")

    def __init__(
        self,
        client: SSHClientConnection,
        api_client: DrovaApiClient | None = None,
        token_cache: ExpiringDict | None = None,
        poll_interval: float = 3.0,
    ):
        super().__init__(client, api_client, token_cache)
        self.poll_interval = poll_interval

    async def run(self) -> bool:
        while True:
            session = await self.api_client.get_latest_session(await self.get_server_id(), await self.get_auth_token())
            if not session:
                return False
            if session.status in (StatusEnum.ABORTED, StatusEnum.FINISHED):
                return True
            await sleep(self.poll_interval)


class WaitNewDesktopSession(BaseDrovaMerchantWindows):
    logger = logger.getChild("WaitNewDesktopSession")

    def __init__(
        self,
        client: SSHClientConnection,
        api_client: DrovaApiClient | None = None,
        token_cache: ExpiringDict | None = None,
        poll_interval: float = 5.0,
    ):
        super().__init__(client, api_client, token_cache)
        self.poll_interval = poll_interval

    async def run(self) -> bool:
        while True:
            servers = await self.get_servers()
            for server_id, auth_token in servers:
                session = await self.api_client.get_latest_session(server_id, auth_token)
                if not session:
                    continue

                if session.status in (
                    StatusEnum.HANDSHAKE,
                    StatusEnum.NEW,
                    StatusEnum.ACTIVE,
                ):
                    if await self.check_desktop_session(session, auth_token):
                        self.set_active_server(server_id, auth_token)
                        return True
            await sleep(self.poll_interval)
