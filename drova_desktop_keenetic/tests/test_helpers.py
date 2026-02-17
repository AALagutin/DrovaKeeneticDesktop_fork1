from unittest.mock import AsyncMock, Mock

import pytest
from asyncssh import SSHCompletedProcess

from drova_desktop_keenetic.common.drova import DrovaApiClient
from drova_desktop_keenetic.common.helpers import CheckDesktop, RebootRequired


def _make_ssh_result(returncode=0, stdout=""):
    result = SSHCompletedProcess()
    result.returncode = returncode
    result.stdout = stdout
    return result


def _make_client(result):
    client = Mock()
    client.run = AsyncMock(return_value=result)
    return client


@pytest.mark.asyncio
async def test_CheckDesktop_refresh_tokens():
    result = _make_ssh_result(
        stdout=r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\85dd80c4-adc1-1111-1111-111111111111
    auth_token    REG_SZ    7a8b78f4-103d-1111-1111-111111111111
"""
    )
    client = _make_client(result)

    api_client = Mock(spec=DrovaApiClient)
    api_client.get_latest_session = AsyncMock(return_value=None)

    helper = CheckDesktop(client, api_client)
    await helper.refresh_actual_tokens()
    assert client.run.call_count == 1

    is_desktop = await helper.run()
    assert is_desktop is False


@pytest.mark.asyncio
async def test_RebootRequiredNoAuthCode():
    result = _make_ssh_result(
        stdout=r"""
HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\85dd80c4-adc1-1111-1111-111111111111
"""
    )
    client = _make_client(result)

    with pytest.raises(RebootRequired):
        helper = CheckDesktop(client)
        await helper.refresh_actual_tokens()

    assert client.run.call_count == 1


@pytest.mark.asyncio
async def test_RebootRequiredBadReturn():
    result = _make_ssh_result(returncode=1, stdout=None)
    client = _make_client(result)

    with pytest.raises(RebootRequired):
        helper = CheckDesktop(client)
        await helper.refresh_actual_tokens()

    assert client.run.call_count == 1
