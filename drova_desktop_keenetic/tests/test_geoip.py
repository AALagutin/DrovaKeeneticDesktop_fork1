"""Tests for geoip.GeoIPClient — dual-source lookup logic."""

from ipaddress import IPv4Address
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from drova_desktop_keenetic.common.geoip import GeoIPClient, GeoIPInfo

_IP = IPv4Address("95.173.1.1")


def _make_client(tmp_path: Path) -> GeoIPClient:
    return GeoIPClient(db_dir=tmp_path / "geoip", update_interval_days=7)


# ---------------------------------------------------------------------------
# _lookup_local — no readers initialised
# ---------------------------------------------------------------------------

def test_lookup_local_returns_none_when_no_readers(tmp_path):
    client = _make_client(tmp_path)
    # No DB files, readers are None
    assert client._lookup_local("95.173.1.1") is None


# ---------------------------------------------------------------------------
# lookup — falls back to API when local DB absent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_falls_back_to_api_when_no_db(tmp_path):
    client = _make_client(tmp_path)
    expected = GeoIPInfo(city="Москва", isp="MegaFon", asn="AS31133")

    with patch.object(client, "_lookup_api", new=AsyncMock(return_value=expected)) as mock_api:
        result = await client.lookup(_IP)

    mock_api.assert_called_once_with(str(_IP))
    assert result == expected


@pytest.mark.asyncio
async def test_lookup_uses_local_db_when_available(tmp_path):
    client = _make_client(tmp_path)
    local_result = GeoIPInfo(city="Санкт-Петербург", isp="Rostelecom", asn="AS12389")

    with patch.object(client, "_lookup_local", return_value=local_result):
        with patch.object(client, "_lookup_api", new=AsyncMock()) as mock_api:
            result = await client.lookup(_IP)

    mock_api.assert_not_called()
    assert result == local_result


# ---------------------------------------------------------------------------
# _lookup_api — success and failure paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_api_success(tmp_path):
    client = _make_client(tmp_path)

    mock_resp = AsyncMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value={"city": "Москва", "isp": "MegaFon", "as": "AS31133"})

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.closed = False

    with patch.object(client, "_get_http", new=AsyncMock(return_value=mock_session)):
        result = await client._lookup_api("95.173.1.1")

    assert result.city == "Москва"
    assert result.isp == "MegaFon"
    assert result.asn == "AS31133"


@pytest.mark.asyncio
async def test_lookup_api_failure_returns_empty_geoipinfo(tmp_path):
    client = _make_client(tmp_path)

    with patch.object(client, "_get_http", new=AsyncMock(side_effect=Exception("network error"))):
        result = await client._lookup_api("95.173.1.1")

    assert result == GeoIPInfo()


@pytest.mark.asyncio
async def test_lookup_returns_empty_when_both_sources_fail(tmp_path):
    """When local DB absent and API fails, lookup returns empty GeoIPInfo."""
    client = _make_client(tmp_path)

    with patch.object(client, "_lookup_api", new=AsyncMock(return_value=GeoIPInfo())):
        result = await client.lookup(_IP)

    assert result == GeoIPInfo()


# ---------------------------------------------------------------------------
# _open_readers — gracefully handles missing maxminddb
# ---------------------------------------------------------------------------

def test_open_readers_without_maxminddb_installed(tmp_path):
    """If maxminddb is not installed, readers remain None without raising."""
    client = _make_client(tmp_path)

    with patch.dict("sys.modules", {"maxminddb": None}):
        client._open_readers()  # should not raise

    assert client._city_reader is None
    assert client._asn_reader is None
