"""FFmpeg screen-streaming helpers.

Builds the FFmpeg command for RTSP streaming with a bottom overlay bar showing:
  - Header title
  - Client IP, city, ISP, ASN (from GeoIP)
  - Session start time and live clock
  - Game title

Stream name is derived from the Gaming PC's IP address:
    192.168.0.10  →  rtsp://monitor:8554/live/192-168-0-10
"""

from dataclasses import dataclass
from datetime import datetime

from drova_desktop_keenetic.common.geoip import GeoIPInfo
from drova_desktop_keenetic.common.host_config import StreamingConfig

# Arial is present on all Windows installations.
_FONT = r"C\:/Windows/Fonts/arial.ttf"


@dataclass
class OverlayParams:
    pc_ip: str          # Gaming PC IP — used to build the RTSP stream key
    client_ip: str      # Drova client IP (SessionsEntity.creator_ip)
    geo: GeoIPInfo      # City, ISP, ASN resolved from client_ip
    game_title: str     # From ProductCatalog
    session_start: datetime


def stream_key(pc_ip: str) -> str:
    """Convert a PC IP to a safe RTSP stream path segment.

    Example: "192.168.0.10" → "192-168-0-10"
    """
    return pc_ip.replace(".", "-")


def _esc(s: str) -> str:
    """Escape a plain string for use inside an FFmpeg drawtext ``text=`` value.

    FFmpeg's filter-graph parser treats ``\\`` as escape, ``:`` as option
    separator and ``'`` as quote delimiter — all must be escaped when they
    appear inside the text payload.
    """
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def _drawtext(text: str, y_expr: str, fontsize: int = 11, fontcolor: str = "white") -> str:
    return (
        f"drawtext=fontfile={_FONT}"
        f":fontsize={fontsize}"
        f":fontcolor={fontcolor}"
        f":x=10:y={y_expr}"
        f":text='{text}'"
    )


def _build_vf(params: OverlayParams, resolution: str) -> str:
    """Build the complete FFmpeg ``-vf`` filter-graph string."""

    # --- Line 2: geo info -------------------------------------------
    geo_parts = [f"Подключен клиент IP\\: {_esc(params.client_ip)}"]
    if params.geo.city:
        geo_parts.append(_esc(params.geo.city))
    if params.geo.isp:
        geo_parts.append(_esc(params.geo.isp))
    if params.geo.asn:
        geo_parts.append(_esc(params.geo.asn))
    geo_text = "  ".join(geo_parts)

    # --- Line 3: session start + live clock --------------------------
    # session_start colons are escaped by _esc; the %{localtime\:...} expansion
    # uses \: to pass colons through FFmpeg's option parser unchanged.
    session_start_esc = _esc(params.session_start.strftime("%Y-%m-%d %H:%M:%S"))
    time_text = (
        f"Начало сеанса\\: {session_start_esc}"
        " | Текущее время\\: %{localtime\\:%H\\:%M\\:%S}"
    )

    # --- Line 4: game title ------------------------------------------
    game_text = f"Игра\\: {_esc(params.game_title)}" if params.game_title else "Игра\\: —"

    # scale=W:H (replace 'x' separator with ':')
    w, h = resolution.split("x", 1)

    filters = [
        f"scale={w}:{h}",
        # Semi-transparent black bar covering 4 lines (≈96 px)
        "drawbox=x=0:y=H-96:w=W:h=96:color=black@0.75:t=fill",
        # Line 1 – header
        _drawtext(
            "Видеорегистрация игровых сеансов DROVA.IO",
            "H-88",
            fontsize=13,
            fontcolor="cyan",
        ),
        # Line 2 – client / geo
        _drawtext(geo_text, "H-66", fontcolor="yellow"),
        # Line 3 – times
        _drawtext(time_text, "H-44"),
        # Line 4 – game
        _drawtext(game_text, "H-22"),
    ]
    return ",".join(filters)


def build_ffmpeg_args_idle(pc_ip: str, cfg: StreamingConfig) -> str:
    """Return an FFmpeg invocation for always-on (session-less) mode.

    Overlay shows the PC IP and a live clock so the stream is identifiable,
    but has no session-specific data (no client IP, no game title).
    """
    rtsp_url = f"rtsp://{cfg.monitor_ip}:{cfg.monitor_port}/live/{stream_key(pc_ip)}"
    w, h = cfg.resolution.split("x", 1)
    filters = [
        f"scale={w}:{h}",
        "drawbox=x=0:y=H-48:w=W:h=48:color=black@0.75:t=fill",
        _drawtext("Видеорегистрация DROVA.IO", "H-40", fontsize=13, fontcolor="cyan"),
        _drawtext(
            f"PC\\: {_esc(pc_ip)}  |  %{{localtime\\:%H\\:%M\\:%S}}",
            "H-20",
            fontcolor="yellow",
        ),
    ]
    vf = ",".join(filters)
    return (
        f'"{cfg.ffmpeg_path}"'
        f" -f gdigrab -framerate {cfg.fps} -i desktop"
        f' -vf "{vf}"'
        f" -c:v {cfg.encoder}"
        f" -preset {cfg.encoder_preset}"
        f" -tune ll"
        f" -rc cbr"
        f" -b:v {cfg.bitrate}"
        f" -f rtsp"
        f" {rtsp_url}"
    )


def build_ffmpeg_args(params: OverlayParams, cfg: StreamingConfig) -> str:
    """Return the FFmpeg invocation string (path + arguments).

    The caller is responsible for wrapping this inside PsExec ``-i 1 -d``
    so that gdigrab can access the interactive desktop session.
    """
    rtsp_url = (
        f"rtsp://{cfg.monitor_ip}:{cfg.monitor_port}/live/{stream_key(params.pc_ip)}"
    )
    vf = _build_vf(params, cfg.resolution)

    return (
        f'"{cfg.ffmpeg_path}"'
        f" -f gdigrab -framerate {cfg.fps} -i desktop"
        f' -vf "{vf}"'
        f" -c:v {cfg.encoder}"
        f" -preset {cfg.encoder_preset}"
        f" -tune ll"
        f" -rc cbr"
        f" -b:v {cfg.bitrate}"
        f" -f rtsp"
        f" {rtsp_url}"
    )
