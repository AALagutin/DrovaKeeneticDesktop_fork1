import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from drova_desktop_keenetic.common.contants import (
    DROVA_CONFIG,
    POLL_INTERVAL_ACTIVE,
    POLL_INTERVAL_IDLE,
    PRODUCT_CATALOG_PATH,
    SHADOW_DEFENDER_DRIVES,
    SHADOW_DEFENDER_PASSWORD,
    WINDOWS_HOST,
    WINDOWS_HOSTS,
    WINDOWS_LOGIN,
    WINDOWS_PASSWORD,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostConfig:
    name: str
    host: str
    login: str
    password: str
    shadow_defender_password: str
    shadow_defender_drives: str


@dataclass(frozen=True)
class StreamingConfig:
    """Configuration for FFmpeg-based screen streaming."""

    enabled: bool = False
    monitor_ip: str = ""
    monitor_port: int = 8554
    fps: int = 2
    resolution: str = "1280x720"
    bitrate: str = "200k"
    ffmpeg_path: str = r"C:\ffmpeg\bin\ffmpeg.exe"
    encoder: str = "h264_nvenc"       # h264_nvenc | h264_amf | h264_qsv | libx264
    encoder_preset: str = "p1"        # p1..p7 for NVENC; ultrafast for libx264
    process_priority: str = "LOW"     # LOW | BELOWNORMAL | NORMAL
    geoip_db_dir: str = "geoip_db"
    geoip_update_interval_days: int = 7


@dataclass(frozen=True)
class AppConfig:
    hosts: list[HostConfig]
    poll_interval_idle: float = 5.0
    poll_interval_active: float = 3.0
    product_catalog_path: str = "drova_products.json"
    streaming: StreamingConfig = field(default_factory=StreamingConfig)


def load_config() -> AppConfig:
    """Load configuration from DROVA_CONFIG json file, or fall back to environment variables."""
    config_path = os.environ.get(DROVA_CONFIG)
    if config_path and Path(config_path).exists():
        return _load_from_json(config_path)
    return _load_from_env()


def _load_from_env() -> AppConfig:
    login = os.environ[WINDOWS_LOGIN]
    password = os.environ[WINDOWS_PASSWORD]
    sd_password = os.environ[SHADOW_DEFENDER_PASSWORD]
    sd_drives = os.environ[SHADOW_DEFENDER_DRIVES]

    poll_idle = float(os.environ.get(POLL_INTERVAL_IDLE, "5"))
    poll_active = float(os.environ.get(POLL_INTERVAL_ACTIVE, "3"))
    catalog_path = os.environ.get(PRODUCT_CATALOG_PATH, "drova_products.json")

    hosts_str = os.environ.get(WINDOWS_HOSTS, "")
    if hosts_str:
        hosts_list = [h.strip() for h in hosts_str.split(",") if h.strip()]
    else:
        hosts_list = [os.environ[WINDOWS_HOST]]

    hosts = []
    for i, host_ip in enumerate(hosts_list):
        hosts.append(
            HostConfig(
                name=f"PC-{i + 1:02d}",
                host=host_ip,
                login=login,
                password=password,
                shadow_defender_password=sd_password,
                shadow_defender_drives=sd_drives,
            )
        )

    logger.info(f"Loaded {len(hosts)} host(s) from environment")
    return AppConfig(hosts=hosts, poll_interval_idle=poll_idle, poll_interval_active=poll_active, product_catalog_path=catalog_path)


def _load_from_json(path: str) -> AppConfig:
    with open(path) as f:
        data = json.load(f)

    defaults = data.get("defaults", {})
    poll_idle = data.get("poll_interval_idle", 5.0)
    poll_active = data.get("poll_interval_active", 3.0)
    catalog_path = data.get("product_catalog_path", "drova_products.json")

    hosts = []
    for i, host_data in enumerate(data["hosts"]):
        hosts.append(
            HostConfig(
                name=host_data.get("name", f"PC-{i + 1:02d}"),
                host=host_data["host"],
                login=host_data.get("login", defaults.get("login", os.environ.get(WINDOWS_LOGIN, ""))),
                password=host_data.get("password", defaults.get("password", os.environ.get(WINDOWS_PASSWORD, ""))),
                shadow_defender_password=host_data.get(
                    "shadow_defender_password",
                    defaults.get("shadow_defender_password", os.environ.get(SHADOW_DEFENDER_PASSWORD, "")),
                ),
                shadow_defender_drives=host_data.get(
                    "shadow_defender_drives",
                    defaults.get("shadow_defender_drives", os.environ.get(SHADOW_DEFENDER_DRIVES, "")),
                ),
            )
        )

    streaming_data = data.get("streaming", {})
    streaming = StreamingConfig(**streaming_data) if streaming_data else StreamingConfig()

    logger.info(f"Loaded {len(hosts)} host(s) from {path}")
    return AppConfig(
        hosts=hosts,
        poll_interval_idle=poll_idle,
        poll_interval_active=poll_active,
        product_catalog_path=catalog_path,
        streaming=streaming,
    )
