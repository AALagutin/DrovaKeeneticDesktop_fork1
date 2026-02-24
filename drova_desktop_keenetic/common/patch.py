import logging
from abc import ABC, abstractmethod
from asyncio import sleep
from configparser import ConfigParser
from pathlib import Path, PureWindowsPath
from typing import Generator

from aiofiles.tempfile import NamedTemporaryFile
from asyncssh import SFTPClient, SSHClientConnection
from pydantic import BaseModel

from drova_desktop_keenetic.common.commands import (
    PsExec,
    RegAdd,
    RegValueType,
)

logger = logging.getLogger(__name__)


class IPatch(ABC):
    NAME: str
    TASKKILL_IMAGE: str

    remote_file_location: PureWindowsPath

    def __init__(self, client: SSHClientConnection, sftp: SFTPClient):
        self.client = client
        self.sftp = sftp

    @abstractmethod
    async def _patch(self, file: Path) -> None: ...

    async def patch(self) -> None:
        async with NamedTemporaryFile("ab") as temp_file:
            await temp_file.close()
            await self.sftp.get(str(self.remote_file_location), str(temp_file.name))
            await self._patch(Path(str(temp_file.name)))
            await self.sftp.put(str(temp_file.name), str(self.remote_file_location))


class EpicGamesAuthDiscard(IPatch):
    logger = logger.getChild("EpicGamesAuthDiscard")
    NAME = "epicgames"
    TASKKILL_IMAGE = "EpicGamesLauncher.exe"

    remote_file_location = PureWindowsPath(r"AppData\Local\EpicGamesLauncher\Saved\Config\WindowsEditor\GameUserSettings.ini")

    async def _patch(self, file: Path) -> None:
        config = ConfigParser(strict=False)
        config.read(file, encoding="UTF-8")
        config.remove_section("RememberMe")
        config.remove_section("Offline")
        with open(file, "w") as f:
            config.write(f)


class SteamAuthDiscard(IPatch):
    logger = logger.getChild("SteamAuthDiscard")
    NAME = "steam"
    TASKKILL_IMAGE = "steam.exe"
    # remote_file_location = PureWindowsPath(r'c:\Program Files (x86)\Steam\config\config.vdf')
    remote_file_location = PureWindowsPath(r"c:\Program Files (x86)\Steam\config\loginusers.vdf")

    async def _patch(self, file: Path) -> None:
        with open(file, mode="w") as f:
            f.write(
                """"users"
{
}"""
            )
        # self.logger.info('Read config.vdf')
        # content_config = file.read().decode()

        # r = re.compile(r'(?P<header>"Authentication"\s+{\s+"RememberedMachineID"\s+{)(\s+"\w+"\s+"\S+)+(?P<end>\s+}\s+})')

        # r.sub('\1\3', content_config)
        # self.logger.info('Write without any authentificated')
        # file.write(content_config.encode())


class UbisoftAuthDiscard(IPatch):
    logger = logger.getChild("UbisoftAuthDiscard")
    NAME = "ubisoft"
    TASKKILL_IMAGE = "upc.exe"

    to_remove = (
        r"AppData\Local\Ubisoft Game Launcher\ConnectSecureStorage.dat",
        r"AppData\Local\Ubisoft Game Launcher\user.dat",
    )

    async def _patch(self, _: Path) -> None:
        return None

    async def patch(self) -> None:
        for file in self.to_remove:
            if await self.sftp.exists(file):
                self.logger.info(f"Remove file {file}")
                await self.sftp.remove(PureWindowsPath(file))


class WargamingAuthDiscard(IPatch):
    logger = logger.getChild("WargamingAuthDiscard")
    NAME = "wargaming"
    TASKKILL_IMAGE = "wgc.exe"

    to_remove = (r"AppData\Roaming\Wargaming.net\GameCenter\user_info.xml",)

    async def _patch(self, _: Path) -> None:
        return None

    async def patch(self) -> None:
        for file in self.to_remove:
            if await self.sftp.exists(file):
                self.logger.info(f"Remove file {file}")
                await self.sftp.remove(PureWindowsPath(file))


class RegistryPatch(BaseModel):
    reg_directory: str
    value_name: str
    value_type: RegValueType
    value: str | int | bytes


class PatchWindowsSettings(IPatch):
    logger = logger.getChild("PatchWindowsSettings")
    NAME = "RegistryPatch"
    TASKKILL_IMAGE = "explorer.exe"

    disable_cmd = RegistryPatch(
        reg_directory=r"HKCU\Software\Policies\Microsoft\Windows\System",
        value_name="DisableCMD",
        value_type=RegValueType.REG_DWORD,
        value=2,
    )
    disable_task_mgr = RegistryPatch(
        reg_directory=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System",
        value_name="DisableTaskMgr",
        value_type=RegValueType.REG_DWORD,
        value=1,
    )
    disable_vbscript = RegistryPatch(
        reg_directory=r"HKCU\Software\Policies\Microsoft\Windows Script Host",
        value_name="Enabled",
        value_type=RegValueType.REG_DWORD,
        value=0,
    )

    explorer_path = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
    disable_poweroff = RegistryPatch(
        reg_directory=explorer_path, value_name="NoClose", value_type=RegValueType.REG_DWORD, value=1
    )
    disable_logoff = RegistryPatch(
        reg_directory=explorer_path, value_name="StartMenuLogoff", value_type=RegValueType.REG_DWORD, value=1
    )
    disable_poweroff_login = RegistryPatch(
        reg_directory=explorer_path, value_name="ShutdownWithoutLogon", value_type=RegValueType.REG_DWORD, value=0
    )
    disable_logout = RegistryPatch(
        reg_directory=explorer_path, value_name="NoLogoff", value_type=RegValueType.REG_DWORD, value=0
    )

    disable_gpedit = RegistryPatch(
        reg_directory=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System",
        value_name="DisableGpedit",
        value_type=RegValueType.REG_DWORD,
        value=1,
    )
    disable_fast_user_switch = RegistryPatch(
        reg_directory=r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
        value_name="HideFastUserSwitching",
        value_type=RegValueType.REG_DWORD,
        value=1,
    )
    disable_mmc = RegistryPatch(
        reg_directory=r"HKCU\Software\Policies\Microsoft\MMC",
        value_name="RestrictToPermittedSnapins",
        value_type=RegValueType.REG_DWORD,
        value=1,
    )

    disable_run_app = RegistryPatch(
        reg_directory=explorer_path,
        value_name="DisallowRun",
        value_type=RegValueType.REG_DWORD,
        value=1,
    )
    blocked_applications = (
        "regedit.exe",
        "powershell.exe",
        "powershell_ise.exe",
        "mmc.exe",
        "gpedit.msc",
        "perfmon.exe",
        "anydesk.exe",
        "rustdesk.exe",
        "ProcessHacker.exe",
        "procexp.exe",
        "autoruns.exe",
        "psexplorer.exe",
        "procexp.exe",
        "procexp64.exe",
        "procexp64a.exe",
        "soundpad.exe",
        "SoundpadService.exe",
    )

    def disable_application(self) -> Generator[RegistryPatch, None, None]:
        for app_index in range(len(self.blocked_applications)):
            app = self.blocked_applications[app_index]
            yield RegistryPatch(
                reg_directory=self.explorer_path, value_name=f"{app_index}", value_type=RegValueType.REG_SZ, value=app
            )

    def _get_patches(self):
        return (
            self.disable_cmd,
            self.disable_task_mgr,
            self.disable_vbscript,
            self.disable_poweroff,
            self.disable_logoff,
            self.disable_poweroff_login,
            self.disable_logout,
            self.disable_gpedit,
            self.disable_fast_user_switch,
            self.disable_mmc,
            self.disable_run_app,
            *self.disable_application(),
        )

    async def _patch(self, _: Path) -> None:
        return None

    async def patch(self) -> None:
        # Every conn.run() opens a new SSH channel.  Instead of opening one
        # channel per reg-add step (N patches × 2 = 2N channels), concatenate
        # all commands with ";" and run them in a single channel.
        # Individual failures are non-fatal (check=False): reg add /f on HKCU
        # paths should always succeed, and any failure will be caught by the
        # surrounding _apply_restrictions() verification step.
        steps: list[str] = []
        for p in self._get_patches():
            steps.append(str(RegAdd(p.reg_directory)))
            steps.append(
                str(RegAdd(p.reg_directory, value_name=p.value_name, value_type=p.value_type, value=p.value))
            )
        await self.client.run("; ".join(steps), check=False)

        await self.client.run("gpupdate /target:user /force", check=True)
        await sleep(1)
        await self.client.run(str(PsExec(command="explorer.exe")), check=False)


ALL_PATCHES = (EpicGamesAuthDiscard, SteamAuthDiscard, UbisoftAuthDiscard, WargamingAuthDiscard, PatchWindowsSettings)
