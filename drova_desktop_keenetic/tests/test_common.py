import pytest

from drova_desktop_keenetic.common.commands import (
    DuplicateAuthCode,
    NotFoundAuthCode,
    PsExec,
    PsExecNotFoundExecutable,
    QWinSta,
    RegQueryEsme,
)


def test_parse_PSExec() -> None:
    with pytest.raises(PsExecNotFoundExecutable):
        PsExec.parseStderrErrorCode(b"Test\r\nNot found executable\r\n\r\n\r\n")

    with pytest.raises(PsExecNotFoundExecutable):
        PsExec.parseStderrErrorCode("Не удается найти указанный файл".encode("windows-1251"))


def test_parse_RegQueryEsme() -> None:
    with pytest.raises(DuplicateAuthCode):
        RegQueryEsme.parseAuthCode(
            r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-888888888888
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-888888888888
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-888888888888
""".encode(
                "windows-1251"
            )
        )

    with pytest.raises(NotFoundAuthCode):
        RegQueryEsme.parseAuthCode(
            r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-888888888888
""".encode(
                "windows-1251"
            )
        )

    server_id, auth_token = RegQueryEsme.parseAuthCode(
        r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-888888888888
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-888888888888
""".encode(
            "windows-1251"
        )
    )
    assert server_id == "8ff8ea03-5b09-4fad-a132-888888888888"
    assert auth_token == "07c43183-61b2-4e18-91cd-888888888888"


_QWINSTA_EN = (
    " SESSIONNAME       USERNAME                 ID  STATE   TYPE        DEVICE\r\n"
    " services                                    0  Disc\r\n"
    ">rdp-tcp#0         user                      2  Active\r\n"
    " rdp-tcp                                 65536  Listen\r\n"
)

_QWINSTA_RU = (
    " ИМЯ_СЕАНСА        ИМЯ_ПОЛЬЗОВАТЕЛЯ         ИД  СОСТОЯНИЕ  ТИП         УСТРОЙСТВО\r\n"
    " services                                    0  Разъедин\r\n"
    ">rdp-tcp#0         user                      3  Активный\r\n"
    " rdp-tcp                                 65536  Прослуш\r\n"
)


def test_qwinsta_parse_active_session_en_bytes() -> None:
    assert QWinSta.parse_active_session_id(_QWINSTA_EN.encode("windows-1251")) == 2


def test_qwinsta_parse_active_session_en_str() -> None:
    assert QWinSta.parse_active_session_id(_QWINSTA_EN) == 2


def test_qwinsta_parse_active_session_ru_bytes() -> None:
    assert QWinSta.parse_active_session_id(_QWINSTA_RU.encode("windows-1251")) == 3


def test_qwinsta_parse_active_session_ru_str() -> None:
    assert QWinSta.parse_active_session_id(_QWINSTA_RU) == 3


def test_qwinsta_parse_active_session_none() -> None:
    assert QWinSta.parse_active_session_id(b"") is None


def test_parse_all_auth_codes() -> None:
    # Empty — no entries
    assert RegQueryEsme.parseAllAuthCodes(b"") == []

    # Single entry
    pairs = RegQueryEsme.parseAllAuthCodes(
        r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\aaaa0001-0000-0000-0000-000000000000
    auth_token    REG_SZ    bbbb0001-0000-0000-0000-000000000000
""".encode("windows-1251")
    )
    assert pairs == [("aaaa0001-0000-0000-0000-000000000000", "bbbb0001-0000-0000-0000-000000000000")]

    # Two servers — each paired correctly
    pairs = RegQueryEsme.parseAllAuthCodes(
        r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\aaaa0001-0000-0000-0000-000000000000
    auth_token    REG_SZ    bbbb0001-0000-0000-0000-000000000000

HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\aaaa0002-0000-0000-0000-000000000000
    auth_token    REG_SZ    bbbb0002-0000-0000-0000-000000000000
""".encode("windows-1251")
    )
    assert len(pairs) == 2
    assert pairs[0] == ("aaaa0001-0000-0000-0000-000000000000", "bbbb0001-0000-0000-0000-000000000000")
    assert pairs[1] == ("aaaa0002-0000-0000-0000-000000000000", "bbbb0002-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# WindowsShutdown
# ---------------------------------------------------------------------------


def test_windows_shutdown_shutdown():
    from drova_desktop_keenetic.common.commands import WindowsShutdown
    cmd = str(WindowsShutdown(reboot=False))
    assert "/s" in cmd
    assert "/r" not in cmd
    assert "/f" in cmd


def test_windows_shutdown_reboot():
    from drova_desktop_keenetic.common.commands import WindowsShutdown
    cmd = str(WindowsShutdown(reboot=True))
    assert "/r" in cmd
    assert "/s" not in cmd
    assert "/f" in cmd


# ---------------------------------------------------------------------------
# GamePCDiagnostic._write_status
# ---------------------------------------------------------------------------


def test_write_status_writes_json(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock
    from drova_desktop_keenetic.common.gamepc_diagnostic import GamePCDiagnostic
    from drova_desktop_keenetic.common.contants import DROVA_STATUS_FILE

    status_file = str(tmp_path / "status.json")
    monkeypatch.setenv(DROVA_STATUS_FILE, status_file)

    diag = GamePCDiagnostic.__new__(GamePCDiagnostic)
    diag.logger = MagicMock()

    diag._write_status(
        skipped=False,
        aborted=False,
        patch_failures=["steam"],
        verification={r"HKCU\key1": True, r"HKCU\key2": False},
    )

    data = json.loads(open(status_file).read())
    assert data["skipped"] is False
    assert data["aborted"] is False
    assert data["patch_failures"] == ["steam"]
    assert data["restrictions_ok"] == 1
    assert data["restrictions_total"] == 2
    assert r"HKCU\key2" in data["restrictions_missing"]
    assert isinstance(data["timestamp"], float)


def test_write_status_noop_when_env_not_set(monkeypatch):
    from unittest.mock import MagicMock
    from drova_desktop_keenetic.common.gamepc_diagnostic import GamePCDiagnostic
    from drova_desktop_keenetic.common.contants import DROVA_STATUS_FILE

    monkeypatch.delenv(DROVA_STATUS_FILE, raising=False)

    diag = GamePCDiagnostic.__new__(GamePCDiagnostic)
    diag.logger = MagicMock()
    # Must not raise
    diag._write_status(skipped=True)


def test_write_status_skipped(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock
    from drova_desktop_keenetic.common.gamepc_diagnostic import GamePCDiagnostic
    from drova_desktop_keenetic.common.contants import DROVA_STATUS_FILE

    status_file = str(tmp_path / "status.json")
    monkeypatch.setenv(DROVA_STATUS_FILE, status_file)

    diag = GamePCDiagnostic.__new__(GamePCDiagnostic)
    diag.logger = MagicMock()
    diag._write_status(skipped=True)

    data = json.loads(open(status_file).read())
    assert data["skipped"] is True
    assert data["restrictions_ok"] == 0
    assert data["patch_failures"] == []
