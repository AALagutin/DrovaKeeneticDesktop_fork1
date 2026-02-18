"""Product catalog with file-based persistence and daily refresh from Drova API.

The catalog fetches all products from the public listfull2 endpoint once per day
and stores them in a JSON file. Individual product details (like use_default_desktop)
are enriched lazily via per-product API calls and cached in the same file.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from drova_desktop_keenetic.common.drova import DrovaApiClient

logger = logging.getLogger(__name__)

CATALOG_REFRESH_SECONDS = 86400  # 24 hours


class ProductCatalog:
    """File-backed product dictionary with daily refresh."""

    def __init__(self, file_path: str | Path = "drova_products.json"):
        self._file_path = Path(file_path)
        self._last_refresh: datetime | None = None
        # product_id (str) -> {"title": str, "use_default_desktop": bool | None}
        self._products: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load catalog from JSON file if it exists."""
        if not self._file_path.exists():
            logger.info(f"Product catalog file {self._file_path} not found, will create on first refresh")
            return
        try:
            with open(self._file_path) as f:
                data = json.load(f)
            raw = data["last_refresh"]
            self._last_refresh = datetime.fromisoformat(raw) if raw else None
            self._products = data.get("products", {})
            logger.info(f"Loaded {len(self._products)} products from catalog (refreshed {self._last_refresh})")
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(f"Corrupt catalog file {self._file_path}, will re-fetch")
            self._last_refresh = None
            self._products = {}

    def _save(self) -> None:
        """Save catalog to JSON file."""
        data = {
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "products": self._products,
        }
        tmp_path = self._file_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self._file_path)
        logger.debug(f"Saved {len(self._products)} products to catalog")

    def needs_refresh(self) -> bool:
        """Check if the catalog needs a refresh (missing or older than 24h)."""
        if self._last_refresh is None:
            return True
        age = (datetime.now(timezone.utc) - self._last_refresh).total_seconds()
        return age > CATALOG_REFRESH_SECONDS

    async def refresh(self, api_client: DrovaApiClient) -> None:
        """Fetch all products from listfull2 and update the catalog file."""
        try:
            items = await api_client.get_product_list()
        except Exception:
            logger.exception("Failed to refresh product catalog from API")
            return

        # Merge: update titles from API, preserve locally-cached use_default_desktop
        for item in items:
            pid = str(item.productId)
            existing = self._products.get(pid, {})
            existing["title"] = item.title
            # preserve use_default_desktop if we already know it
            existing.setdefault("use_default_desktop", None)
            self._products[pid] = existing

        self._last_refresh = datetime.now(timezone.utc)
        self._save()
        logger.info(f"Refreshed product catalog: {len(items)} products from API")

    def get_use_default_desktop(self, product_id: UUID) -> bool | None:
        """Look up use_default_desktop for a product. Returns None if unknown."""
        entry = self._products.get(str(product_id))
        if entry is None:
            return None
        return entry.get("use_default_desktop")

    def set_use_default_desktop(self, product_id: UUID, title: str, value: bool) -> None:
        """Cache use_default_desktop for a product and save to file."""
        pid = str(product_id)
        entry = self._products.get(pid, {})
        entry["title"] = title
        entry["use_default_desktop"] = value
        self._products[pid] = entry
        self._save()

    @property
    def product_count(self) -> int:
        return len(self._products)
