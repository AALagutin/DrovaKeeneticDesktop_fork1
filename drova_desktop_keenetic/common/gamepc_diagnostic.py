import json
import logging
import os
import time
from asyncio import sleep

from asyncssh import SSHClientConnection

from drova_desktop_keenetic.common.commands import RegDeleteKey, RegQuery, ShadowDefenderCLI, TaskKill
from drova_desktop_keenetic.common.contants import DROVA_STATUS_FILE, SHADOW_DEFENDER_DRIVES, SHADOW_DEFENDER_PASSWORD
from drova_desktop_keenetic.common.drova import StatusEnum, check_credentials, get_latest_session
from drova_desktop_keenetic.common.helpers import BaseDrovaMerchantWindows, RebootRequired
from drova_desktop_keenetic.common.patch import ALL_PATCHES, PatchWindowsSettings, RegistryPatch

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (StatusEnum.NEW, StatusEnum.HANDSHAKE, StatusEnum.ACTIVE)


class GamePCDiagnostic(BaseDrovaMerchantWindows):
    """
    Запускается при старте воркера.
    Если нет активных сессий — проверяет механизм ограничений:
    входит в SD, применяет все патчи, проверяет реестр, логирует отчёт,
    выходит из SD+reboot (откатывает все изменения).
    """

    def __init__(self, client: SSHClientConnection, host: str):
        super().__init__(client)
        self.host = host
        # host встроен в имя логгера — не нужен префикс в каждом сообщении
        self.logger = logger.getChild(host)

    # ------------------------------------------------------------------
    # Registry cleanup
    # ------------------------------------------------------------------

    async def _cleanup_stale_registrations(self) -> None:
        """Remove invalid server registrations from registry.

        Queries all (server_id, auth_token) pairs, verifies each via Drova API,
        and deletes entries that return a non-200 response.
        """
        from drova_desktop_keenetic.common.commands import RegQueryEsme

        result = await self.client.run(str(RegQueryEsme()))
        if result.exit_status or result.returncode:
            return

        stdout = result.stdout.encode() if isinstance(result.stdout, str) else (result.stdout or b"")
        all_pairs = RegQueryEsme.parseAllAuthCodes(stdout)

        if len(all_pairs) <= 1:
            return

        self.logger.warning("cleanup: %d server registrations found, verifying each", len(all_pairs))

        for server_id, auth_token in all_pairs:
            try:
                valid = await check_credentials(server_id, auth_token)
            except Exception:
                self.logger.warning("cleanup: %s... — network error, skipping", server_id[:8])
                continue

            if valid:
                self.logger.info("cleanup: %s... — valid, keeping", server_id[:8])
            else:
                reg_path = rf"HKEY_LOCAL_MACHINE\SOFTWARE\ITKey\Esme\servers\{server_id}"
                self.logger.warning("cleanup: %s... — invalid, deleting", server_id[:8])
                await self.client.run(str(RegDeleteKey(reg_path=reg_path)))

    # ------------------------------------------------------------------
    # Session check
    # ------------------------------------------------------------------

    async def _has_active_sessions(self) -> bool:
        try:
            server_id = await self.get_server_id()
            auth_token = await self.get_auth_token()
        except RebootRequired:
            self.logger.warning("sessions: auth tokens unavailable — host needs reboot")
            return True

        session = await get_latest_session(server_id, auth_token)
        if session and session.status in _ACTIVE_STATUSES:
            self.logger.info("sessions: active (%s) — diagnostic skipped", session.status)
            return True
        self.logger.info("sessions: none")
        return False

    # ------------------------------------------------------------------
    # Shadow Defender
    # ------------------------------------------------------------------

    def _sd_log(self, label: str, result) -> None:
        """Одна строка: SD <label>: OK/FAILED [— первая строка вывода]."""
        first_out = next(
            (l.strip() for l in (result.stdout or "").splitlines() if l.strip()), ""
        )
        if result.exit_status:
            self.logger.warning(
                "SD %s: FAILED code=%s%s", label, result.exit_status,
                f" — {first_out}" if first_out else "",
            )
        else:
            self.logger.info(
                "SD %s: OK%s", label, f" — {first_out}" if first_out else ""
            )
        if stderr := (result.stderr or "").strip():
            self.logger.warning("SD %s stderr: %s", label, stderr[:200])

    async def _sd_log_status(self) -> None:
        """Одна строка: SD status: Drive C: Protected; Drive D: Not protected."""
        result = await self.client.run(
            str(ShadowDefenderCLI(password=os.environ[SHADOW_DEFENDER_PASSWORD], actions=["list"]))
        )
        lines = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
        self.logger.info("SD status: %s", "; ".join(lines) if lines else "(no output)")

    async def _sd_enter(self) -> None:
        result = await self.client.run(
            str(ShadowDefenderCLI(
                password=os.environ[SHADOW_DEFENDER_PASSWORD],
                actions=["enter"],
                drives=os.environ[SHADOW_DEFENDER_DRIVES],
            ))
        )
        self._sd_log("enter", result)
        await sleep(2)
        await self._sd_log_status()

    async def _sd_exit_reboot(self) -> None:
        result = await self.client.run(
            str(ShadowDefenderCLI(
                password=os.environ[SHADOW_DEFENDER_PASSWORD],
                actions=["exit", "reboot"],
                drives=os.environ[SHADOW_DEFENDER_DRIVES],
            ))
        )
        self._sd_log("exit+reboot", result)

    # ------------------------------------------------------------------
    # Apply restrictions
    # ------------------------------------------------------------------

    async def _apply_restrictions(self) -> list[str]:
        """Применяет все патчи. Возвращает список имён упавших патчей."""
        failed: list[str] = []
        async with self.client.start_sftp_client() as sftp:
            for patch_class in ALL_PATCHES:
                if patch_class.TASKKILL_IMAGE:
                    await self.client.run(str(TaskKill(image=patch_class.TASKKILL_IMAGE)))
                await sleep(0.2)
                try:
                    await patch_class(self.client, sftp).patch()
                    self.logger.info("patch %-20s OK", patch_class.NAME)
                except Exception:
                    self.logger.warning("patch %-20s FAILED", patch_class.NAME, exc_info=True)
                    failed.append(patch_class.NAME)
        return failed

    # ------------------------------------------------------------------
    # Verify restrictions
    # ------------------------------------------------------------------

    async def _verify_patch(self, patch: RegistryPatch) -> bool:
        result = await self.client.run(str(RegQuery(patch.reg_directory, patch.value_name)))
        if result.exit_status != 0:
            return False
        return RegQuery.parse_value(result.stdout) is not None

    async def _verify_all_restrictions(self) -> dict[str, bool]:
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
        total = len(verification)
        ok_count = sum(1 for v in verification.values() if v)
        missing = [k for k, v in verification.items() if not v]

        if not missing:
            self.logger.info("restrictions: %d/%d OK", ok_count, total)
        else:
            self.logger.warning(
                "restrictions: %d/%d OK — %d MISSING", ok_count, total, len(missing)
            )
            for key in missing:
                self.logger.warning("  missing: %s", key)

    def _write_status(
        self,
        *,
        skipped: bool = False,
        aborted: bool = False,
        patch_failures: list[str] | None = None,
        verification: dict[str, bool] | None = None,
    ) -> None:
        """Persist diagnostic results to DROVA_STATUS_FILE for the web server to read."""
        status_file = os.environ.get(DROVA_STATUS_FILE)
        if not status_file:
            return

        verification = verification or {}
        ok_count = sum(1 for v in verification.values() if v)
        missing = [k for k, v in verification.items() if not v]

        data = {
            "timestamp": time.time(),
            "skipped": skipped,
            "aborted": aborted,
            "patch_failures": patch_failures or [],
            "restrictions_ok": ok_count,
            "restrictions_total": len(verification),
            "restrictions_missing": missing,
        }
        try:
            with open(status_file, "w") as f:
                json.dump(data, f)
        except Exception:
            self.logger.warning("diagnostic: failed to write status file %s", status_file)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self.logger.info("diagnostic: start")
        patch_failures: list[str] = []
        verification: dict[str, bool] = {}
        skipped = False
        aborted = False
        try:
            await self._cleanup_stale_registrations()
            if await self._has_active_sessions():
                skipped = True
                return

            await self._sd_enter()

            try:
                patch_failures = await self._apply_restrictions()
                if patch_failures:
                    self.logger.warning("patches failed: %s", ", ".join(patch_failures))

                verification = await self._verify_all_restrictions()
                self._log_report(verification)
            finally:
                await self._sd_exit_reboot()

        except RebootRequired:
            self.logger.warning("diagnostic: aborted — RebootRequired")
            aborted = True
        except Exception:
            self.logger.exception("diagnostic: error")
            aborted = True
        finally:
            self._write_status(
                skipped=skipped,
                aborted=aborted,
                patch_failures=patch_failures,
                verification=verification,
            )

        self.logger.info("diagnostic: done")
