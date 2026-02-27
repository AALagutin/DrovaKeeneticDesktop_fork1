import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field

from asyncssh import connect as connect_ssh
from asyncssh.misc import ChannelOpenError

logger = logging.getLogger(__name__)


@dataclass
class HostDiag:
    """Cached results from the periodic background SSH probe (read-only checks)."""

    # True = SSH reachable with current credentials; False = unreachable/wrong password; None = not checked yet
    ssh_ok: bool | None = None
    # True = at least one drive is in Shadow Defender shadow mode; False = no drives protected; None = not checked
    shadow_mode: bool | None = None
    # True = all PatchWindowsSettings registry keys are present; False = some missing; None = not checked
    restrictions_ok: bool | None = None
    # None = not checked; "idle" = no active Drova session; "desktop" = active desktop session;
    # "non_desktop" = active but non-desktop session
    session_state: str | None = None
    # time.time() timestamp of the last completed probe, or None if never probed
    last_checked: float | None = None


@dataclass
class HostEntry:
    host: str
    login: str | None
    password: str | None
    enabled: bool = True
    process: asyncio.subprocess.Process | None = field(default=None, compare=False)
    diag: HostDiag = field(default_factory=HostDiag, compare=False)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self.process.returncode if self.process is not None else None


class WorkerManager:
    def __init__(self, config_path: str) -> None:
        self.config_path = config_path
        self.config: dict = {}
        self.hosts: dict[str, HostEntry] = {}

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def load_config(self) -> None:
        with open(self.config_path) as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"config.json contains invalid JSON: {e}") from e

        self._validate_config(config)

        defaults = config.get("defaults", {})
        # Build new state fully before mutating self, so a parse error mid-loop
        # does not leave self.hosts in a partial state.
        new_hosts: dict[str, HostEntry] = {}
        for h in config["hosts"]:
            host = h["host"]
            new_hosts[host] = HostEntry(
                host=host,
                login=h.get("login") or defaults.get("login"),
                password=h.get("password") or defaults.get("password"),
                enabled=h.get("enabled", True),
            )

        self.config = config
        self.hosts.clear()
        self.hosts.update(new_hosts)

    @staticmethod
    def _validate_config(config: dict) -> None:
        if not isinstance(config.get("hosts"), list):
            raise ValueError("config.json: 'hosts' must be a list")
        for i, h in enumerate(config["hosts"]):
            if not isinstance(h, dict) or "host" not in h:
                raise ValueError(f"config.json: hosts[{i}] is missing required 'host' field")

    def save_config(self) -> None:
        defaults = self.config.get("defaults", {})
        hosts_list = []
        for entry in self.hosts.values():
            h: dict = {"host": entry.host}
            if not entry.enabled:
                h["enabled"] = False
            if entry.login and entry.login != defaults.get("login"):
                h["login"] = entry.login
            if entry.password and entry.password != defaults.get("password"):
                h["password"] = entry.password
            hosts_list.append(h)
        self.config["hosts"] = hosts_list

        # Atomic write: write to a temp file in the same directory, then
        # rename over the target. os.replace() is atomic on POSIX when both
        # paths are on the same filesystem, so a crash mid-write never leaves
        # config.json empty or truncated.
        config_dir = os.path.dirname(os.path.abspath(self.config_path))
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.config, f, indent=2)
            os.replace(tmp_path, self.config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _worker_cmd() -> list[str]:
        return [
            sys.executable,
            "-c",
            "from drova_desktop_keenetic.bin.drova_poll import run_async_main; run_async_main()",
        ]

    async def start_all(self) -> None:
        for host, entry in self.hosts.items():
            if entry.enabled:
                await self.start_worker(host)
        asyncio.create_task(self._monitor_loop(), name="worker-monitor")
        asyncio.create_task(self._probe_loop(), name="host-probe")

    async def _monitor_loop(self) -> None:
        """Periodically check for crashed workers and restart them."""
        while True:
            await asyncio.sleep(10)
            for host, entry in list(self.hosts.items()):
                if entry.enabled and entry.process is not None and entry.process.returncode is not None:
                    logger.warning(
                        "manager: worker for %s exited with code %d — restarting",
                        host,
                        entry.process.returncode,
                    )
                    await asyncio.sleep(5)
                    try:
                        await self.start_worker(host)
                    except Exception:
                        logger.exception("manager: failed to restart worker for %s", host)

    async def start_worker(self, host: str) -> None:
        entry = self.hosts.get(host)
        if entry is None:
            raise ValueError(f"Host {host!r} not found")
        if entry.running:
            return

        defaults = self.config.get("defaults", {})
        env = os.environ.copy()
        env["WINDOWS_HOST"] = host
        env["WINDOWS_LOGIN"] = entry.login or defaults.get("login", "")
        env["WINDOWS_PASSWORD"] = entry.password or defaults.get("password", "")
        # Remove DROVA_CONFIG so the subprocess runs in single-host mode
        env.pop("DROVA_CONFIG", None)

        process = await asyncio.create_subprocess_exec(*self._worker_cmd(), env=env)
        entry.process = process
        entry.enabled = True
        self.save_config()
        logger.info("manager: started worker pid=%d host=%s", process.pid, host)

    async def stop_worker(self, host: str) -> None:
        entry = self.hosts.get(host)
        if entry is None:
            raise ValueError(f"Host {host!r} not found")

        if entry.process and entry.process.returncode is None:
            entry.process.terminate()
            try:
                await asyncio.wait_for(entry.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                entry.process.kill()
                await entry.process.wait()
            logger.info("manager: stopped worker host=%s", host)

        entry.enabled = False
        self.save_config()

    async def add_host(self, host: str, login: str | None = None, password: str | None = None) -> None:
        if host in self.hosts:
            raise ValueError(f"Host {host!r} already exists")
        self.hosts[host] = HostEntry(host=host, login=login, password=password, enabled=True)
        self.save_config()
        await self.start_worker(host)

    async def remove_host(self, host: str) -> None:
        if host not in self.hosts:
            raise ValueError(f"Host {host!r} not found")
        await self.stop_worker(host)
        del self.hosts[host]
        self.save_config()

    # ------------------------------------------------------------------
    # SSH helpers
    # ------------------------------------------------------------------

    def _ssh_connect_args(self, entry: HostEntry) -> dict:
        defaults = self.config.get("defaults", {})
        return dict(
            host=entry.host,
            username=entry.login or defaults.get("login", ""),
            password=entry.password or defaults.get("password", ""),
            known_hosts=None,
            encoding="windows-1251",
            connect_timeout=10,
        )

    # ------------------------------------------------------------------
    # Host power control
    # ------------------------------------------------------------------

    async def reboot_host(self, host: str) -> None:
        entry = self.hosts.get(host)
        if entry is None:
            raise ValueError(f"Host {host!r} not found")
        from drova_desktop_keenetic.common.commands import WindowsShutdown

        try:
            async with connect_ssh(**self._ssh_connect_args(entry)) as conn:
                await conn.run(str(WindowsShutdown(reboot=True)), timeout=10)
        except (ChannelOpenError, OSError):
            # The host likely accepted the command and terminated the connection
            pass
        logger.info("manager: reboot command sent to host=%s", host)

    async def shutdown_host(self, host: str) -> None:
        entry = self.hosts.get(host)
        if entry is None:
            raise ValueError(f"Host {host!r} not found")
        from drova_desktop_keenetic.common.commands import WindowsShutdown

        try:
            async with connect_ssh(**self._ssh_connect_args(entry)) as conn:
                await conn.run(str(WindowsShutdown(reboot=False)), timeout=10)
        except (ChannelOpenError, OSError):
            pass
        logger.info("manager: shutdown command sent to host=%s", host)

    # ------------------------------------------------------------------
    # Background host probe
    # ------------------------------------------------------------------

    async def _probe_shadow_mode(self, conn) -> bool | None:
        sd_password = os.environ.get("SHADOW_DEFENDER_PASSWORD", "")
        if not sd_password:
            return None
        from drova_desktop_keenetic.common.commands import ShadowDefenderCLI

        result = await conn.run(
            str(ShadowDefenderCLI(password=sd_password, actions=["list"])),
            timeout=10,
        )
        lines = (result.stdout or "").splitlines()
        protected = [l for l in lines if "Protected" in l and "Not protected" not in l]
        return len(protected) > 0

    async def _probe_restrictions(self, conn) -> bool | None:
        from drova_desktop_keenetic.common.commands import RegQuery
        from drova_desktop_keenetic.common.patch import PatchWindowsSettings

        patches = list(PatchWindowsSettings(None, None)._get_patches())  # type: ignore[arg-type]
        sem = asyncio.Semaphore(5)

        async def _check_one(patch) -> bool:
            async with sem:
                result = await conn.run(
                    str(RegQuery(patch.reg_directory, patch.value_name)), timeout=5
                )
                return result.exit_status == 0 and RegQuery.parse_value(result.stdout) is not None

        results = await asyncio.gather(*[_check_one(p) for p in patches], return_exceptions=True)
        ok = sum(1 for r in results if r is True)
        return ok == len(patches)

    async def _probe_session(self, conn) -> str | None:
        from drova_desktop_keenetic.common.drova import StatusEnum, get_latest_session
        from drova_desktop_keenetic.common.helpers import BaseDrovaMerchantWindows, RebootRequired

        try:
            checker = BaseDrovaMerchantWindows(conn)
            server_id = await checker.get_server_id()
            auth_token = await checker.get_auth_token()
            session = await get_latest_session(server_id, auth_token)
            if not session:
                return "idle"
            if session.status in (StatusEnum.NEW, StatusEnum.HANDSHAKE, StatusEnum.ACTIVE):
                is_desktop = await checker.check_desktop_session(session)
                return "desktop" if is_desktop else "non_desktop"
            return "idle"
        except RebootRequired:
            return None

    async def _probe_host_once(self, entry: HostEntry) -> None:
        diag = entry.diag
        try:
            async with connect_ssh(**self._ssh_connect_args(entry)) as conn:
                diag.ssh_ok = True
                try:
                    diag.shadow_mode = await self._probe_shadow_mode(conn)
                except Exception:
                    logger.debug("probe: shadow_mode check failed for %s", entry.host, exc_info=True)
                    diag.shadow_mode = None
                try:
                    diag.restrictions_ok = await self._probe_restrictions(conn)
                except Exception:
                    logger.debug("probe: restrictions check failed for %s", entry.host, exc_info=True)
                    diag.restrictions_ok = None
                try:
                    diag.session_state = await self._probe_session(conn)
                except Exception:
                    logger.debug("probe: session check failed for %s", entry.host, exc_info=True)
                    diag.session_state = None
        except (ChannelOpenError, OSError):
            diag.ssh_ok = False
            diag.shadow_mode = None
            diag.restrictions_ok = None
            diag.session_state = None
        except Exception:
            # asyncssh.PermissionDenied and other auth errors
            diag.ssh_ok = False
            diag.shadow_mode = None
            diag.restrictions_ok = None
            diag.session_state = None
            logger.debug("probe: connection error for %s", entry.host, exc_info=True)
        finally:
            diag.last_checked = time.time()

    async def _safe_probe(self, entry: HostEntry) -> None:
        try:
            await asyncio.wait_for(self._probe_host_once(entry), timeout=90)
        except asyncio.TimeoutError:
            logger.warning("probe: timed out for %s", entry.host)
        except Exception:
            logger.exception("probe: unexpected error for %s", entry.host)

    async def _probe_loop(self) -> None:
        """Background loop: probe all hosts every 30 s (first run after 15 s startup delay)."""
        await asyncio.sleep(15)
        while True:
            entries = list(self.hosts.values())
            if entries:
                await asyncio.gather(*[self._safe_probe(e) for e in entries], return_exceptions=True)
            await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> list[dict]:
        result = []
        for entry in self.hosts.values():
            if entry.process is not None and entry.process.returncode is not None:
                status = "error" if entry.process.returncode != 0 else "stopped"
            elif entry.running:
                status = "running"
            elif entry.enabled:
                status = "stopped"
            else:
                status = "disabled"
            d = entry.diag
            result.append(
                {
                    "host": entry.host,
                    "enabled": entry.enabled,
                    "running": entry.running,
                    "status": status,
                    "pid": entry.process.pid if entry.process else None,
                    "exit_code": entry.exit_code,
                    "diag": {
                        "ssh_ok": d.ssh_ok,
                        "shadow_mode": d.shadow_mode,
                        "restrictions_ok": d.restrictions_ok,
                        "session_state": d.session_state,
                        "last_checked": d.last_checked,
                    },
                }
            )
        return result
