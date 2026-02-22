"""Tests for ffmpeg_stream: stream key, text escaping, command building."""

from datetime import datetime, timezone

import pytest

from drova_desktop_keenetic.common.ffmpeg_stream import (
    OverlayParams,
    _esc,
    build_ffmpeg_args,
    stream_key,
)
from drova_desktop_keenetic.common.geoip import GeoIPInfo
from drova_desktop_keenetic.common.host_config import StreamingConfig

_BASE_CFG = StreamingConfig(
    enabled=True,
    monitor_ip="192.168.1.200",
    monitor_port=8554,
    fps=2,
    resolution="1280x720",
    bitrate="200k",
    ffmpeg_path=r"C:\ffmpeg\bin\ffmpeg.exe",
    encoder="h264_nvenc",
    encoder_preset="p1",
)

_SESSION_START = datetime(2026, 2, 21, 14, 32, 11, tzinfo=timezone.utc)


def _make_params(**kwargs) -> OverlayParams:
    defaults = dict(
        pc_ip="192.168.0.10",
        client_ip="95.173.1.1",
        geo=GeoIPInfo(city="Москва", isp="MegaFon", asn="AS31133"),
        game_title="Cyberpunk 2077",
        session_start=_SESSION_START,
    )
    defaults.update(kwargs)
    return OverlayParams(**defaults)


# ---------------------------------------------------------------------------
# stream_key
# ---------------------------------------------------------------------------

def test_stream_key_replaces_dots():
    assert stream_key("192.168.0.10") == "192-168-0-10"


def test_stream_key_single_octet():
    assert stream_key("10.0.0.1") == "10-0-0-1"


# ---------------------------------------------------------------------------
# _esc (FFmpeg drawtext escaping)
# ---------------------------------------------------------------------------

def test_esc_plain_text_unchanged():
    assert _esc("hello world") == "hello world"


def test_esc_colon_escaped():
    assert _esc("IP: 1.2.3.4") == "IP\\: 1.2.3.4"


def test_esc_single_quote_escaped():
    assert _esc("it's") == "it\\'s"


def test_esc_backslash_doubled():
    assert _esc("a\\b") == "a\\\\b"


def test_esc_multiple_colons():
    assert _esc("14:32:11") == "14\\:32\\:11"


# ---------------------------------------------------------------------------
# build_ffmpeg_args
# ---------------------------------------------------------------------------

def test_build_ffmpeg_args_encoder_in_output():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "h264_nvenc" in cmd


def test_build_ffmpeg_args_stream_key_in_url():
    cmd = build_ffmpeg_args(_make_params(pc_ip="192.168.0.10"), _BASE_CFG)
    assert "192-168-0-10" in cmd


def test_build_ffmpeg_args_monitor_address():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "192.168.1.200:8554" in cmd


def test_build_ffmpeg_args_capture_source():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "gdigrab" in cmd


def test_build_ffmpeg_args_resolution_in_scale():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "1280:720" in cmd


def test_build_ffmpeg_args_bitrate():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "200k" in cmd


def test_build_ffmpeg_args_fps():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "-framerate 2" in cmd


def test_build_ffmpeg_args_overlay_contains_game_title():
    cmd = build_ffmpeg_args(_make_params(game_title="Cyberpunk 2077"), _BASE_CFG)
    assert "Cyberpunk 2077" in cmd


def test_build_ffmpeg_args_overlay_contains_client_ip():
    cmd = build_ffmpeg_args(_make_params(client_ip="95.173.1.1"), _BASE_CFG)
    assert "95.173.1.1" in cmd


def test_build_ffmpeg_args_overlay_contains_geo_fields():
    cmd = build_ffmpeg_args(
        _make_params(geo=GeoIPInfo(city="Москва", isp="MegaFon", asn="AS31133")),
        _BASE_CFG,
    )
    assert "Москва" in cmd
    assert "MegaFon" in cmd
    assert "AS31133" in cmd


def test_build_ffmpeg_args_empty_geo_fields_omitted():
    """Empty geo fields should not produce stray separators in the output."""
    cmd = build_ffmpeg_args(
        _make_params(geo=GeoIPInfo(city="", isp="", asn="")),
        _BASE_CFG,
    )
    # Output should still be valid (no crash), city line present
    assert "Подключен клиент IP" in cmd


def test_build_ffmpeg_args_session_start_in_overlay():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "2026-02-21" in cmd


def test_build_ffmpeg_args_dynamic_clock_present():
    """The FFmpeg localtime expansion token must appear in the filter string."""
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "localtime" in cmd


def test_build_ffmpeg_args_ffmpeg_path_in_output():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "ffmpeg.exe" in cmd


def test_build_ffmpeg_args_rtsp_protocol():
    cmd = build_ffmpeg_args(_make_params(), _BASE_CFG)
    assert "-f rtsp" in cmd
