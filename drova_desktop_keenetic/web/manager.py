import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HostEntry:
    host: str
    login: str | None
    password: str | None
    enabled: bool = True
    process: asyncio.subprocess.Process | None = field(default=None, compare=False)

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

    def load_config(self) -> None:
        with open(self.config_path) as f:
            self.config = json.load(f)
        defaults = self.config.get("defaults", {})
        self.hosts.clear()
        for h in self.config.get("hosts", []):
            host = h["host"]
            self.hosts[host] = HostEntry(
                host=host,
                login=h.get("login") or defaults.get("login"),
                password=h.get("password") or defaults.get("password"),
                enabled=h.get("enabled", True),
            )

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
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)

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
            result.append(
                {
                    "host": entry.host,
                    "enabled": entry.enabled,
                    "running": entry.running,
                    "status": status,
                    "pid": entry.process.pid if entry.process else None,
                    "exit_code": entry.exit_code,
                }
            )
        return result
