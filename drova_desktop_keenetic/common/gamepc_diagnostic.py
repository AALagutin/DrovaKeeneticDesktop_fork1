import logging
import os
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import RegQuery, ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.contants import SHADOW_DEFENDER_DRIVES, SHADOW_DEFENDER_PASSWORD
from drova_desktop_keenetic.common.drova import StatusEnum, get_latest_session
from drova_desktop_keenetic.common.helpers import BaseDrovaMerchantWindows, RebootRequired
from drova_desktop_keenetic.common.patch import ALL_PATCHES, PatchWindowsSettings, RegistryPatch

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (StatusEnum.NEW, StatusEnum.HANDSHAKE, StatusEnum.ACTIVE)


class GamePCDiagnostic(BaseDrovaMerchantWindows):
    """
    Запускается при старте воркера.
    Если нет активных сессий — проверяет, что механизм ограничений работает:
    входит в режим SD, применяет все ограничения, проверяет реестр,
    выводит отчёт в лог, выходит из SD (что откатывает все изменения).
    """

    logger = logger.getChild("GamePCDiagnostic")

    def __init__(self, client: SSHClientConnection, host: str):
        super().__init__(client)
        self.host = host

    # ------------------------------------------------------------------
    # Session check
    # ------------------------------------------------------------------

    async def _has_active_sessions(self) -> bool:
        try:
            server_id = await self.get_server_id()
            auth_token = await self.get_auth_token()
        except RebootRequired:
            self.logger.warning(f"[{self.host}] Auth tokens not available — host needs reboot")
            return True  # treat as "busy", skip diagnostic

        session = await get_latest_session(server_id, auth_token)
        if session and session.status in _ACTIVE_STATUSES:
            return True
        return False

    # ------------------------------------------------------------------
    # Shadow Defender helpers
    # ------------------------------------------------------------------

    async def _sd_enter(self) -> None:
        self.logger.info(f"[{self.host}] Entering Shadow Defender mode")
        await self.client.run(
            str(
                ShadowDefenderCLI(
                    password=os.environ[SHADOW_DEFENDER_PASSWORD],
                    actions=["enter"],
                    drives=os.environ[SHADOW_DEFENDER_DRIVES],
                )
            )
        )
        await sleep(2)

    async def _sd_exit_reboot(self) -> None:
        self.logger.info(f"[{self.host}] Exiting Shadow Defender and rebooting (cleanup)")
        await self.client.run(
            str(
                ShadowDefenderCLI(
                    password=os.environ[SHADOW_DEFENDER_PASSWORD],
                    actions=["exit", "reboot"],
                    drives=os.environ[SHADOW_DEFENDER_DRIVES],
                )
            )
        )

    # ------------------------------------------------------------------
    # Apply restrictions
    # ------------------------------------------------------------------

    async def _apply_restrictions(self) -> None:
        self.logger.info(f"[{self.host}] Applying all restrictions")
        async with self.client.start_sftp_client() as sftp:
            for patch_class in ALL_PATCHES:
                self.logger.info(f"[{self.host}] Patch: {patch_class.NAME}")
                if patch_class.TASKKILL_IMAGE:
                    await self.client.run(str(TaskKill(image=patch_class.TASKKILL_IMAGE)))
                await sleep(0.2)
                patcher = patch_class(self.client, sftp)
                try:
                    await patcher.patch()
                except Exception:
                    self.logger.exception(f"[{self.host}] Patch {patch_class.NAME} failed — skipped")

    # ------------------------------------------------------------------
    # Verify restrictions
    # ------------------------------------------------------------------

    async def _verify_patch(self, patch: RegistryPatch) -> bool:
        result = await self.client.run(
            str(RegQuery(patch.reg_directory, patch.value_name))
        )
        if result.exit_status != 0:
            return False
        return RegQuery.parse_value(result.stdout) is not None

    async def _verify_all_restrictions(self) -> dict[str, bool]:
        # PatchWindowsSettings does not use sftp, so None is safe here
        settings = PatchWindowsSettings(self.client, None)  # type: ignore[arg-type]
        results: dict[str, bool] = {}
        for patch in settings._get_patches():
            key = f"{patch.reg_directory}\\{patch.value_name}"
            results[key] = await self._verify_patch(patch)
        return results

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def _log_report(self, verification: dict[str, bool]) -> None:
        ok_count = sum(1 for v in verification.values() if v)
        fail_count = len(verification) - ok_count
        overall = "OK" if fail_count == 0 else f"FAILED ({fail_count} missing)"

        self.logger.info(f"[{self.host}] ===== GamePC Diagnostic Report — {overall} =====")
        for key, ok in verification.items():
            mark = "+" if ok else "!"
            self.logger.info(f"[{self.host}]   [{mark}] {key}")
        self.logger.info(
            f"[{self.host}] ===== End Report: {ok_count}/{len(verification)} restrictions set ====="
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self.logger.info(f"[{self.host}] Starting startup diagnostic")

        try:
            if await self._has_active_sessions():
                self.logger.info(f"[{self.host}] Active session found — diagnostic skipped")
                return

            self.logger.info(f"[{self.host}] No active sessions — running restriction test")

            await self._sd_enter()

            try:
                await self._apply_restrictions()
                verification = await self._verify_all_restrictions()
                self._log_report(verification)
            finally:
                # Always exit SD + reboot to revert all test changes
                await self._sd_exit_reboot()

        except RebootRequired:
            self.logger.warning(f"[{self.host}] RebootRequired during diagnostic — skipping")
        except Exception:
            self.logger.exception(f"[{self.host}] Diagnostic error")
