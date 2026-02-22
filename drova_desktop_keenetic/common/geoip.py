"""Dual-source GeoIP client.

Priority:
  1. Local MaxMind GeoLite2 MMDB databases (downloaded from GitHub, refreshed weekly).
  2. ip-api.com REST API as fallback when local DB is unavailable or lookup fails.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

_GITHUB_CITY_URL = (
    "https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-City.mmdb"
)
_GITHUB_ASN_URL = (
    "https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-ASN.mmdb"
)
_IP_API_URL = "http://ip-api.com/json/{ip}?fields=city,isp,as&lang=ru"


@dataclass
class GeoIPInfo:
    city: str = ""
    isp: str = ""
    asn: str = ""   # e.g. "AS31133"


class GeoIPClient:
    """Looks up city, ISP and ASN for an IPv4 address.

    Uses a local MMDB database as the primary source and falls back to
    ip-api.com when the database is unavailable or the lookup fails.
    The database is downloaded from GitHub on first use and refreshed
    automatically according to *update_interval_days*.
    """

    def __init__(self, db_dir: Path, update_interval_days: int = 7) -> None:
        self._db_dir = db_dir
        self._city_path = db_dir / "GeoLite2-City.mmdb"
        self._asn_path = db_dir / "GeoLite2-ASN.mmdb"
        self._city_reader = None
        self._asn_reader = None
        self._update_interval = timedelta(days=update_interval_days)
        self._last_update: datetime | None = None
        self._lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            )
        return self._session

    async def initialize(self) -> None:
        """Download databases if needed and open readers. Call once at startup."""
        await self._ensure_databases()

    async def update_loop(self) -> None:
        """Background task: refresh databases every *update_interval_days*."""
        while True:
            await asyncio.sleep(self._update_interval.total_seconds())
            async with self._lock:
                logger.info("GeoIP: scheduled database update")
                await self._download_databases()

    async def lookup(self, ip: IPv4Address) -> GeoIPInfo:
        """Return GeoIP info for *ip*. Never raises; returns empty strings on total failure."""
        result = self._lookup_local(str(ip))
        if result is not None:
            return result
        logger.debug(f"GeoIP local miss for {ip}, falling back to ip-api.com")
        return await self._lookup_api(str(ip))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_databases(self) -> None:
        needs = (
            not self._city_path.exists()
            or not self._asn_path.exists()
            or self._last_update is None
            or datetime.now() - self._last_update > self._update_interval
        )
        if needs:
            await self._download_databases()
        self._open_readers()

    async def _download_databases(self) -> None:
        self._db_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info("GeoIP: downloading City database from GitHub…")
            await self._download_file(_GITHUB_CITY_URL, self._city_path)
            logger.info("GeoIP: downloading ASN database from GitHub…")
            await self._download_file(_GITHUB_ASN_URL, self._asn_path)
            self._last_update = datetime.now()
            self._open_readers()
            logger.info("GeoIP databases updated successfully")
        except Exception:
            logger.exception("GeoIP: failed to download databases — will use API fallback")

    async def _download_file(self, url: str, path: Path) -> None:
        http = await self._get_http()
        async with http.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            data = await resp.read()
        path.write_bytes(data)

    def _open_readers(self) -> None:
        try:
            import maxminddb  # type: ignore[import]
        except ImportError:
            logger.warning("maxminddb not installed – local GeoIP lookup disabled")
            return

        if self._city_reader:
            self._city_reader.close()
            self._city_reader = None
        if self._asn_reader:
            self._asn_reader.close()
            self._asn_reader = None

        if self._city_path.exists():
            try:
                self._city_reader = maxminddb.open_database(str(self._city_path))
            except Exception:
                logger.exception("GeoIP: failed to open City database")
        if self._asn_path.exists():
            try:
                self._asn_reader = maxminddb.open_database(str(self._asn_path))
            except Exception:
                logger.exception("GeoIP: failed to open ASN database")

    def _lookup_local(self, ip: str) -> GeoIPInfo | None:
        if not self._city_reader or not self._asn_reader:
            return None
        try:
            city_rec = self._city_reader.get(ip) or {}
            asn_rec = self._asn_reader.get(ip) or {}

            city_names = city_rec.get("city", {}).get("names", {})
            city = city_names.get("ru") or city_names.get("en", "")

            asn_num = asn_rec.get("autonomous_system_number", "")
            isp = asn_rec.get("autonomous_system_organization", "")

            return GeoIPInfo(
                city=city,
                isp=isp,
                asn=f"AS{asn_num}" if asn_num else "",
            )
        except Exception:
            logger.debug(f"GeoIP: local lookup error for {ip}", exc_info=True)
            return None

    async def _lookup_api(self, ip: str) -> GeoIPInfo:
        try:
            http = await self._get_http()
            async with http.get(_IP_API_URL.format(ip=ip)) as resp:
                resp.raise_for_status()
                data = await resp.json()
            return GeoIPInfo(
                city=data.get("city", ""),
                isp=data.get("isp", ""),
                asn=data.get("as", ""),
            )
        except Exception:
            logger.warning(f"GeoIP: API lookup failed for {ip}", exc_info=True)
            return GeoIPInfo()

    async def close(self) -> None:
        if self._city_reader:
            self._city_reader.close()
        if self._asn_reader:
            self._asn_reader.close()
        if self._session and not self._session.closed:
            await self._session.close()
