import asyncio
import json
import os

from drova_desktop_keenetic.common.contants import DROVA_CONFIG, SHADOW_DEFENDER_DRIVES, SHADOW_DEFENDER_PASSWORD
from drova_desktop_keenetic.common.drova_poll import DrovaPoll


def _load_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


async def _run_multihost(config: dict) -> None:
    defaults = config.get("defaults", {})

    if sd_password := defaults.get("shadow_defender_password"):
        os.environ.setdefault(SHADOW_DEFENDER_PASSWORD, sd_password)
    if sd_drives := defaults.get("shadow_defender_drives"):
        os.environ.setdefault(SHADOW_DEFENDER_DRIVES, sd_drives)

    workers = [
        DrovaPoll(
            windows_host=host["host"],
            windows_login=host.get("login", defaults.get("login")),
            windows_password=host.get("password", defaults.get("password")),
        ).serve(wait_forever=True)
        for host in config["hosts"]
    ]
    await asyncio.gather(*workers)


def run_async_main():
    if DROVA_CONFIG in os.environ:
        config = _load_config(os.environ[DROVA_CONFIG])
        asyncio.run(_run_multihost(config))
    else:
        asyncio.run(DrovaPoll().serve(True))


if __name__ == "__main__":
    run_async_main()
