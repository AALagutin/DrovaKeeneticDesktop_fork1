import os
from logging import INFO, StreamHandler, basicConfig
from logging.handlers import RotatingFileHandler
from pathlib import Path

from drova_desktop_keenetic.common.contants import DROVA_CONFIG, WINDOWS_HOST

config_path = os.environ.get(DROVA_CONFIG)
if config_path:
    log_suffix = Path(config_path).stem
elif WINDOWS_HOST in os.environ:
    log_suffix = os.environ[WINDOWS_HOST]
else:
    log_suffix = "app"

log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"
ch = StreamHandler()
handler_rotating = RotatingFileHandler(f"app.{log_suffix}.log", maxBytes=1024 * 1024, backupCount=5)

basicConfig(level=INFO, handlers=(handler_rotating, ch), format=log_format, datefmt=date_format)
