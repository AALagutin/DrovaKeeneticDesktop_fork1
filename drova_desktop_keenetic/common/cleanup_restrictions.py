"""
Detects and reverses stuck registry/firewall restrictions.

These restrictions are applied by BeforeConnect (via PatchWindowsSettings and
PatchNetworkHardening in patch.py) at the start of each session.  Normally,
AfterDisconnect triggers a reboot which exits Shadow Defender and discards all
changes.  If the client was force-killed (or SD was absent/broken), the reboot
never happens and the restrictions remain permanently active.

This module runs via the existing SSH connection (as the logged-in Administrator),
so HKCU resolves to the user's hive directly — no SYSTEM/HKU-SID tricks needed.
"""

import asyncio
import logging

from asyncssh import SSHClientConnection

logger = logging.getLogger(__name__)

# Registry key and value used to detect whether restrictions are currently applied.
# DisableTaskMgr is always set by PatchWindowsSettings and is easy to query.
_SENTINEL_PATH  = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System"
_SENTINEL_VALUE = "DisableTaskMgr"

_EXPLORER_PATH = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"

# All (registry_path, value_name) pairs to delete.
# value_name=None means delete the entire key (for the DisallowRun subkey).
# Order does not matter — they are executed in parallel.
_REG_DELETIONS: tuple[tuple[str, str | None], ...] = (
    # PatchWindowsSettings.disable_cmd
    (r"HKCU\Software\Policies\Microsoft\Windows\System",
     "DisableCMD"),
    # PatchWindowsSettings.disable_task_mgr
    (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System",
     "DisableTaskMgr"),
    # PatchWindowsSettings.disable_gpedit
    (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System",
     "DisableGpedit"),
    # PatchWindowsSettings.disable_vbscript
    (r"HKCU\Software\Policies\Microsoft\Windows Script Host",
     "Enabled"),
    # PatchWindowsSettings.disable_poweroff / disable_logoff / disable_poweroff_login / disable_logout
    (_EXPLORER_PATH, "NoClose"),
    (_EXPLORER_PATH, "StartMenuLogoff"),
    (_EXPLORER_PATH, "ShutdownWithoutLogon"),
    (_EXPLORER_PATH, "NoLogoff"),
    # PatchWindowsSettings.disable_run_app (the DisallowRun enabler flag)
    (_EXPLORER_PATH, "DisallowRun"),
    # DisallowRun subkey (in case it was created as a proper Windows subkey)
    (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer\DisallowRun",
     None),
    # PatchWindowsSettings.disable_mmc
    (r"HKCU\Software\Policies\Microsoft\MMC",
     "RestrictToPermittedSnapins"),
    # PatchWindowsSettings.disable_fast_user_switch  (HKLM, not HKCU)
    (r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
     "HideFastUserSwitching"),
)

# patch.py stores blocked app names as numbered string values 0..N directly
# under _EXPLORER_PATH (len(PatchWindowsSettings.blocked_applications) == 17).
_BLOCKED_APP_COUNT = 17  # indices 0 … 16

# Firewall rules added by PatchNetworkHardening.
_FIREWALL_CLEANUPS = (
    'netsh advfirewall firewall delete rule name="Block SMB Out"',
    'netsh advfirewall firewall delete rule name="Block NetBIOS Out"',
    'netsh advfirewall firewall set rule group="Network Discovery" new enable=Yes',
)


def _reg_delete(path: str, value: str | None) -> str:
    """Build a reg.exe delete command string."""
    if value is None:
        return f'reg delete "{path}" /f'
    return f'reg delete "{path}" /v "{value}" /f'


class CleanupRestrictions:
    """
    Detects and reverses all restrictions left over from an interrupted session.

    Usage::

        cleanup = CleanupRestrictions(ssh_conn)
        if await cleanup.is_stuck():
            await cleanup.run()
    """

    logger = logger.getChild("CleanupRestrictions")

    def __init__(self, client: SSHClientConnection) -> None:
        self.client = client

    async def is_stuck(self) -> bool:
        """
        Return True if DisableTaskMgr is present under the current user's HKCU.
        This key is always set by PatchWindowsSettings and is absent on a clean PC.
        """
        result = await self.client.run(
            f'reg query "{_SENTINEL_PATH}" /v {_SENTINEL_VALUE}',
            check=False,
        )
        return result.exit_status == 0

    async def run(self) -> None:
        """
        Remove all registry restrictions and firewall rules.
        Errors from individual deletions are silently ignored (the key may already
        be absent if the restriction was partially reverted or never applied).
        """
        self.logger.info("Removing stuck restrictions...")

        # Build all reg-delete commands
        reg_cmds = [_reg_delete(path, value) for path, value in _REG_DELETIONS]
        # Numbered DisallowRun entries stored directly under the Explorer key
        reg_cmds += [_reg_delete(_EXPLORER_PATH, str(i)) for i in range(_BLOCKED_APP_COUNT)]

        # Execute all registry deletions concurrently
        await asyncio.gather(
            *(self.client.run(cmd, check=False) for cmd in reg_cmds),
            return_exceptions=True,
        )

        # Firewall cleanup (order-independent, sequential is fine)
        for cmd in _FIREWALL_CLEANUPS:
            await self.client.run(cmd, check=False)

        # Refresh group policy so changes take effect in the current session
        await self.client.run("gpupdate /target:user /force", check=False)

        self.logger.info("Stuck restrictions removed successfully.")
