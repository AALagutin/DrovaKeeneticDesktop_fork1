import pytest

from drova_desktop_keenetic.common.commands import (
    NotFoundAuthCode,
    PsExec,
    PsExecNotFoundExecutable,
    RegQueryEsme,
)


def test_parse_PSExec() -> None:
    with pytest.raises(PsExecNotFoundExecutable):
        PsExec.parseStderrErrorCode(b"Test\r\nNot found executable\r\n\r\n\r\n")

    with pytest.raises(PsExecNotFoundExecutable):
        PsExec.parseStderrErrorCode("Не удается найти указанный файл".encode("windows-1251"))


def test_parse_RegQueryEsme_single_server() -> None:
    with pytest.raises(NotFoundAuthCode):
        RegQueryEsme.parseAuthCode(
            r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-888888888888
""".encode(
                "windows-1251"
            )
        )

    servers = RegQueryEsme.parseAuthCode(
        r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-888888888888
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-888888888888
""".encode(
            "windows-1251"
        )
    )
    assert len(servers) == 1
    assert servers[0] == ("8ff8ea03-5b09-4fad-a132-888888888888", "07c43183-61b2-4e18-91cd-888888888888")


def test_parse_RegQueryEsme_multiple_servers() -> None:
    servers = RegQueryEsme.parseAuthCode(
        r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-111111111111
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-aaaaaaaaaaaa

HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\8ff8ea03-5b09-4fad-a132-222222222222
    auth_token    REG_SZ    07c43183-61b2-4e18-91cd-bbbbbbbbbbbb
""".encode(
            "windows-1251"
        )
    )
    assert len(servers) == 2
    assert servers[0] == ("8ff8ea03-5b09-4fad-a132-111111111111", "07c43183-61b2-4e18-91cd-aaaaaaaaaaaa")
    assert servers[1] == ("8ff8ea03-5b09-4fad-a132-222222222222", "07c43183-61b2-4e18-91cd-bbbbbbbbbbbb")
