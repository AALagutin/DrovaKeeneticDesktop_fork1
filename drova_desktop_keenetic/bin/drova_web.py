import asyncio
import logging
import os

from drova_desktop_keenetic.common.contants import (
    DROVA_CONFIG,
    DROVA_WEB_PASSWORD,
    DROVA_WEB_PORT,
    DROVA_WEB_USER,
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
)
from drova_desktop_keenetic.web.manager import WorkerManager
from drova_desktop_keenetic.web.server import run_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _main() -> None:
    config_path = os.environ[DROVA_CONFIG]

    manager = WorkerManager(config_path)
    manager.load_config()

    defaults = manager.config.get("defaults", {})
    if sd_password := defaults.get("shadow_defender_password"):
        os.environ.setdefault(SHADOW_DEFENDER_PASSWORD, sd_password)
    if sd_drives := defaults.get("shadow_defender_drives"):
        os.environ.setdefault(SHADOW_DEFENDER_DRIVES, sd_drives)

    port = int(os.environ.get(DROVA_WEB_PORT, "8080"))
    user = os.environ.get(DROVA_WEB_USER, "admin")
    password = os.environ.get(DROVA_WEB_PASSWORD, "")

    if not password:
        logger.warning("DROVA_WEB_PASSWORD is not set — web UI has no password protection!")

    await run_server(manager, port, user, password)
    await manager.start_all()
    logger.info("web: all enabled workers started, UI available on http://0.0.0.0:%d", port)

    await asyncio.Event().wait()


def run_async_main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run_async_main()
