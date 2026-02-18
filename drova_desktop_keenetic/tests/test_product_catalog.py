import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from drova_desktop_keenetic.common.drova import DrovaApiClient, ProductListItem
from drova_desktop_keenetic.common.product_catalog import CATALOG_REFRESH_SECONDS, ProductCatalog


@pytest.fixture
def catalog_path(tmp_path):
    return tmp_path / "test_products.json"


def test_empty_catalog(catalog_path):
    """Catalog starts empty when no file exists."""
    catalog = ProductCatalog(catalog_path)
    assert catalog.product_count == 0
    assert catalog.needs_refresh() is True


def test_load_save_roundtrip(catalog_path):
    """Catalog saves and loads correctly."""
    catalog = ProductCatalog(catalog_path)
    catalog.set_use_default_desktop(
        UUID("11111111-1111-1111-1111-111111111111"), "Test Game", True
    )

    # Reload from file
    catalog2 = ProductCatalog(catalog_path)
    assert catalog2.product_count == 1
    assert catalog2.get_use_default_desktop(UUID("11111111-1111-1111-1111-111111111111")) is True


def test_get_unknown_product(catalog_path):
    """Unknown product returns None."""
    catalog = ProductCatalog(catalog_path)
    assert catalog.get_use_default_desktop(UUID("99999999-9999-9999-9999-999999999999")) is None


def test_needs_refresh_fresh(catalog_path):
    """Catalog does not need refresh if recently updated."""
    data = {
        "last_refresh": datetime.now(timezone.utc).isoformat(),
        "products": {},
    }
    with open(catalog_path, "w") as f:
        json.dump(data, f)

    catalog = ProductCatalog(catalog_path)
    assert catalog.needs_refresh() is False


def test_needs_refresh_stale(catalog_path):
    """Catalog needs refresh if older than 24h."""
    old_time = datetime.now(timezone.utc) - timedelta(seconds=CATALOG_REFRESH_SECONDS + 100)
    data = {
        "last_refresh": old_time.isoformat(),
        "products": {},
    }
    with open(catalog_path, "w") as f:
        json.dump(data, f)

    catalog = ProductCatalog(catalog_path)
    assert catalog.needs_refresh() is True


def test_corrupt_file(catalog_path):
    """Corrupt catalog file is handled gracefully."""
    with open(catalog_path, "w") as f:
        f.write("not valid json{{{")

    catalog = ProductCatalog(catalog_path)
    assert catalog.product_count == 0
    assert catalog.needs_refresh() is True


@pytest.mark.asyncio
async def test_refresh_from_api(catalog_path):
    """Refresh fetches products and saves to file."""
    api_client = Mock(spec=DrovaApiClient)
    api_client.get_product_list = AsyncMock(
        return_value=[
            ProductListItem(productId=UUID("aaaa1111-1111-1111-1111-111111111111"), title="Game A"),
            ProductListItem(productId=UUID("bbbb2222-2222-2222-2222-222222222222"), title="Game B"),
        ]
    )

    catalog = ProductCatalog(catalog_path)
    await catalog.refresh(api_client)

    assert catalog.product_count == 2
    assert catalog.needs_refresh() is False

    # Check file was written
    with open(catalog_path) as f:
        data = json.load(f)
    assert len(data["products"]) == 2
    assert data["products"]["aaaa1111-1111-1111-1111-111111111111"]["title"] == "Game A"


@pytest.mark.asyncio
async def test_refresh_preserves_use_default_desktop(catalog_path):
    """Refresh from API preserves locally-cached use_default_desktop values."""
    pid = UUID("aaaa1111-1111-1111-1111-111111111111")

    catalog = ProductCatalog(catalog_path)
    catalog.set_use_default_desktop(pid, "Game A", True)

    api_client = Mock(spec=DrovaApiClient)
    api_client.get_product_list = AsyncMock(
        return_value=[
            ProductListItem(productId=pid, title="Game A Updated"),
        ]
    )

    await catalog.refresh(api_client)

    # Title updated, but use_default_desktop preserved
    assert catalog.get_use_default_desktop(pid) is True
    assert catalog.product_count == 1


@pytest.mark.asyncio
async def test_refresh_api_failure(catalog_path):
    """Failed API call during refresh doesn't corrupt existing data."""
    pid = UUID("aaaa1111-1111-1111-1111-111111111111")

    catalog = ProductCatalog(catalog_path)
    catalog.set_use_default_desktop(pid, "Game A", True)

    api_client = Mock(spec=DrovaApiClient)
    api_client.get_product_list = AsyncMock(side_effect=Exception("Network error"))

    await catalog.refresh(api_client)

    # Existing data preserved
    assert catalog.get_use_default_desktop(pid) is True
    assert catalog.product_count == 1
