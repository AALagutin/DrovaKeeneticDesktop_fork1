from logging import INFO, StreamHandler, basicConfig
from logging.handlers import RotatingFileHandler

log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"
ch = StreamHandler()
handler_rotating = RotatingFileHandler("app.log", maxBytes=1024 * 1024, backupCount=5)

basicConfig(level=INFO, handlers=(handler_rotating, ch), format=log_format, datefmt=date_format)
