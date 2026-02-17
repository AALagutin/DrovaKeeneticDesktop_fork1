import asyncio

from drova_desktop_keenetic.common.drova_poll import DrovaManager
from drova_desktop_keenetic.common.host_config import load_config


def run_async_main():
    config = load_config()
    asyncio.run(DrovaManager(config).run())


if __name__ == "__main__":
    run_async_main()
