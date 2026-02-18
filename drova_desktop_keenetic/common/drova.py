import logging
from datetime import datetime
from enum import StrEnum
from ipaddress import IPv4Address
from pathlib import PureWindowsPath
from uuid import UUID

import aiohttp
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

URL_SESSIONS = "https://services.drova.io/session-manager/sessions?"
URL_PRODUCT = "https://services.drova.io/server-manager/product/get/{product_id}"
UUID_DESKTOP = UUID("9fd0eb43-b2bb-4ce3-93b8-9df63f209098")


class StatusEnum(StrEnum):
    NEW = "NEW"
    HANDSHAKE = "HANDSHAKE"
    ACTIVE = "ACTIVE"

    ABORTED = "ABORTED"
    FINISHED = "FINISHED"


class SessionsEntity(BaseModel):
    uuid: UUID
    product_id: UUID
    client_id: UUID
    created_on: datetime
    finished_on: datetime | None = None
    status: StatusEnum
    creator_ip: IPv4Address
    abort_comment: str | None = None
    score: int | None = None
    score_reason: int | None = None
    score_text: str | None = None
    billing_type: str | None = None


class SessionsResponse(BaseModel):
    sessions: list[SessionsEntity]


class ProductInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: UUID
    game_path: PureWindowsPath
    work_path: PureWindowsPath
    args: str
    use_default_desktop: bool
    title: str


class DrovaApiClient:
    """Shared HTTP client for Drova API with connection pooling and timeouts.

    A single instance should be shared across all workers to reuse TCP connections.
    """

    def __init__(self, timeout: int = 15):
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def get_latest_session(self, server_id: str, auth_token: str) -> SessionsEntity | None:
        session = await self._get_session()
        async with session.get(
            URL_SESSIONS, data={"serveri_id": server_id}, headers={"X-Auth-Token": auth_token}
        ) as resp:
            if resp.status == 401:
                logger.debug(f"Unauthorized for server {server_id} (expired token)")
                return None
            if resp.status != 200:
                logger.warning(f"Unexpected status {resp.status} for server {server_id}")
                return None
            data = SessionsResponse(**await resp.json())
            if not data.sessions:
                return None
            return data.sessions[0]

    async def get_product_info(self, product_id: UUID, auth_token: str) -> ProductInfo:
        session = await self._get_session()
        async with session.get(
            URL_PRODUCT.format(product_id=product_id), headers={"X-Auth-Token": auth_token}
        ) as resp:
            resp.raise_for_status()
            return ProductInfo(**await resp.json())
