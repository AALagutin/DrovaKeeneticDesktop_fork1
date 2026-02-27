"""
Tests for WorkerManager — production-readiness checks.

Covers: config load/save, worker lifecycle (start/stop/add/remove),
status reporting, duplicate-prevention, env isolation, crash recovery.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from drova_desktop_keenetic.web.manager import HostEntry, WorkerManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "defaults": {"login": "Admin", "password": "pass"},
    "hosts": [
        {"host": "10.0.0.1"},
        {"host": "10.0.0.2", "login": "Other", "password": "other"},
        {"host": "10.0.0.3", "enabled": False},
    ],
}


def make_fake_process(pid: int = 1234, returncode: int | None = None) -> MagicMock:
    proc = MagicMock()
    proc.pid = pid
    proc.returncode = returncode
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps(BASE_CONFIG))
    return str(path)


@pytest.fixture
def manager(config_file):
    m = WorkerManager(config_file)
    m.load_config()
    return m


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_all_hosts_loaded(self, manager):
        assert set(manager.hosts) == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}

    def test_default_login_applied(self, manager):
        entry = manager.hosts["10.0.0.1"]
        assert entry.login == "Admin"
        assert entry.password == "pass"

    def test_host_overrides_default(self, manager):
        entry = manager.hosts["10.0.0.2"]
        assert entry.login == "Other"
        assert entry.password == "other"

    def test_enabled_false_respected(self, manager):
        assert manager.hosts["10.0.0.3"].enabled is False

    def test_enabled_default_is_true(self, manager):
        assert manager.hosts["10.0.0.1"].enabled is True


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_default_fields_not_duplicated(self, manager, config_file):
        manager.save_config()
        saved = json.loads(open(config_file).read())
        host_map = {h["host"]: h for h in saved["hosts"]}
        # Default login/password must not appear on the plain host entry
        assert "login" not in host_map["10.0.0.1"]
        assert "password" not in host_map["10.0.0.1"]

    def test_override_fields_preserved(self, manager, config_file):
        manager.save_config()
        saved = json.loads(open(config_file).read())
        host_map = {h["host"]: h for h in saved["hosts"]}
        assert host_map["10.0.0.2"]["login"] == "Other"

    def test_enabled_false_written(self, manager, config_file):
        manager.hosts["10.0.0.1"].enabled = False
        manager.save_config()
        saved = json.loads(open(config_file).read())
        host_map = {h["host"]: h for h in saved["hosts"]}
        assert host_map["10.0.0.1"]["enabled"] is False

    def test_enabled_true_not_written(self, manager, config_file):
        # enabled=True is the default; should not be serialised
        manager.save_config()
        saved = json.loads(open(config_file).read())
        host_map = {h["host"]: h for h in saved["hosts"]}
        assert "enabled" not in host_map["10.0.0.1"]

    def test_roundtrip_preserves_defaults_block(self, manager, config_file):
        manager.save_config()
        saved = json.loads(open(config_file).read())
        assert saved["defaults"]["login"] == "Admin"


# ---------------------------------------------------------------------------
# start_worker
# ---------------------------------------------------------------------------


class TestStartWorker:
    @pytest.mark.asyncio
    async def test_spawns_subprocess(self, manager, mocker):
        fake_proc = make_fake_process(pid=5001)
        mock_exec = AsyncMock(return_value=fake_proc)
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        await manager.start_worker("10.0.0.1")

        mock_exec.assert_called_once()
        assert manager.hosts["10.0.0.1"].process is fake_proc

    @pytest.mark.asyncio
    async def test_env_has_correct_credentials(self, manager, mocker, monkeypatch):
        monkeypatch.setenv("DROVA_CONFIG", "/some/config.json")
        fake_proc = make_fake_process()
        mock_exec = AsyncMock(return_value=fake_proc)
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        await manager.start_worker("10.0.0.2")

        env = mock_exec.call_args.kwargs["env"]
        assert env["WINDOWS_HOST"] == "10.0.0.2"
        assert env["WINDOWS_LOGIN"] == "Other"
        assert env["WINDOWS_PASSWORD"] == "other"

    @pytest.mark.asyncio
    async def test_drova_config_removed_from_env(self, manager, mocker, monkeypatch):
        """Subprocess must run in single-host mode — DROVA_CONFIG must be absent."""
        monkeypatch.setenv("DROVA_CONFIG", "/some/config.json")
        mock_exec = AsyncMock(return_value=make_fake_process())
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        await manager.start_worker("10.0.0.1")

        env = mock_exec.call_args.kwargs["env"]
        assert "DROVA_CONFIG" not in env

    @pytest.mark.asyncio
    async def test_idempotent_when_already_running(self, manager, mocker):
        mock_exec = AsyncMock(return_value=make_fake_process())
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        await manager.start_worker("10.0.0.1")
        await manager.start_worker("10.0.0.1")  # second call

        assert mock_exec.call_count == 1

    @pytest.mark.asyncio
    async def test_sets_enabled_true_for_disabled_host(self, manager, mocker):
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=make_fake_process()))

        await manager.start_worker("10.0.0.3")  # was disabled

        assert manager.hosts["10.0.0.3"].enabled is True

    @pytest.mark.asyncio
    async def test_unknown_host_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager.start_worker("9.9.9.9")


# ---------------------------------------------------------------------------
# stop_worker
# ---------------------------------------------------------------------------


class TestStopWorker:
    @pytest.mark.asyncio
    async def test_terminates_process(self, manager, mocker):
        fake_proc = make_fake_process(pid=5001)
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc))
        await manager.start_worker("10.0.0.1")

        await manager.stop_worker("10.0.0.1")

        fake_proc.terminate.assert_called_once()
        assert manager.hosts["10.0.0.1"].enabled is False

    @pytest.mark.asyncio
    async def test_kills_on_timeout(self, manager, mocker):
        fake_proc = make_fake_process(pid=5001)
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc))
        mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)
        await manager.start_worker("10.0.0.1")

        await manager.stop_worker("10.0.0.1")

        fake_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_if_not_running(self, manager):
        """stop_worker on a never-started host must not raise, just set enabled=False."""
        await manager.stop_worker("10.0.0.1")  # no process attached

        assert manager.hosts["10.0.0.1"].enabled is False

    @pytest.mark.asyncio
    async def test_unknown_host_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager.stop_worker("9.9.9.9")

    @pytest.mark.asyncio
    async def test_persists_disabled_state(self, manager, mocker, config_file):
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=make_fake_process()))
        await manager.start_worker("10.0.0.1")

        await manager.stop_worker("10.0.0.1")

        saved = json.loads(open(config_file).read())
        host_map = {h["host"]: h for h in saved["hosts"]}
        assert host_map["10.0.0.1"]["enabled"] is False


# ---------------------------------------------------------------------------
# add_host / remove_host
# ---------------------------------------------------------------------------


class TestAddHost:
    @pytest.mark.asyncio
    async def test_adds_and_starts_worker(self, manager, mocker):
        mock_exec = AsyncMock(return_value=make_fake_process(pid=9999))
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        await manager.add_host("10.0.0.99", login="L", password="P")

        assert "10.0.0.99" in manager.hosts
        assert manager.hosts["10.0.0.99"].running is True
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_raises(self, manager, mocker):
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=make_fake_process()))
        with pytest.raises(ValueError, match="already exists"):
            await manager.add_host("10.0.0.1")

    @pytest.mark.asyncio
    async def test_persisted_to_config(self, manager, mocker, config_file):
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=make_fake_process()))
        await manager.add_host("10.0.0.99")

        saved = json.loads(open(config_file).read())
        hosts = [h["host"] for h in saved["hosts"]]
        assert "10.0.0.99" in hosts


class TestRemoveHost:
    @pytest.mark.asyncio
    async def test_stops_and_removes(self, manager, mocker):
        fake_proc = make_fake_process()
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc))
        await manager.start_worker("10.0.0.1")

        await manager.remove_host("10.0.0.1")

        assert "10.0.0.1" not in manager.hosts
        fake_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_persisted_to_config(self, manager, mocker, config_file):
        mocker.patch("asyncio.create_subprocess_exec", AsyncMock(return_value=make_fake_process()))
        await manager.start_worker("10.0.0.1")
        await manager.remove_host("10.0.0.1")

        saved = json.loads(open(config_file).read())
        hosts = [h["host"] for h in saved["hosts"]]
        assert "10.0.0.1" not in hosts

    @pytest.mark.asyncio
    async def test_unknown_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager.remove_host("9.9.9.9")


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_running(self, manager):
        manager.hosts["10.0.0.1"].process = make_fake_process(pid=111)

        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.1")
        assert item["status"] == "running"
        assert item["running"] is True
        assert item["pid"] == 111

    def test_stopped_no_process(self, manager):
        # enabled=True, no process attached
        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.1")
        assert item["status"] == "stopped"
        assert item["running"] is False
        assert item["pid"] is None

    def test_disabled(self, manager):
        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.3")
        assert item["status"] == "disabled"
        assert item["running"] is False

    def test_error_on_nonzero_exit(self, manager):
        manager.hosts["10.0.0.1"].process = make_fake_process(returncode=1)
        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.1")
        assert item["status"] == "error"
        assert item["exit_code"] == 1

    def test_stopped_on_zero_exit(self, manager):
        manager.hosts["10.0.0.1"].process = make_fake_process(returncode=0)
        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.1")
        assert item["status"] == "stopped"

    def test_all_hosts_returned(self, manager):
        statuses = manager.get_status()
        assert len(statuses) == 3


# ---------------------------------------------------------------------------
# start_all
# ---------------------------------------------------------------------------


class TestStartAll:
    @pytest.mark.asyncio
    async def test_starts_only_enabled_hosts(self, manager, mocker):
        mock_exec = AsyncMock(return_value=make_fake_process())
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)
        # Cancel monitor task immediately so it doesn't interfere
        mocker.patch("asyncio.create_task")

        await manager.start_all()

        # 10.0.0.1 and 10.0.0.2 are enabled; 10.0.0.3 is disabled
        assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_disabled_host_not_started(self, manager, mocker):
        mock_exec = AsyncMock(return_value=make_fake_process())
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)
        mocker.patch("asyncio.create_task")

        await manager.start_all()

        started_hosts = [call.kwargs["env"]["WINDOWS_HOST"] for call in mock_exec.call_args_list]
        assert "10.0.0.3" not in started_hosts


# ---------------------------------------------------------------------------
# _monitor_loop — crash recovery
# ---------------------------------------------------------------------------


class TestMonitorLoop:
    @pytest.mark.asyncio
    async def test_restarts_crashed_enabled_worker(self, manager, mocker):
        """A worker that exits unexpectedly must be restarted by the monitor."""
        crashed_proc = make_fake_process(pid=100, returncode=1)
        manager.hosts["10.0.0.1"].process = crashed_proc
        manager.hosts["10.0.0.1"].enabled = True

        new_proc = make_fake_process(pid=200)
        mock_exec = AsyncMock(return_value=new_proc)
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        # Allow two sleeps (outer + inner delay), cancel on third
        sleep_calls = 0

        async def fake_sleep(t):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                raise asyncio.CancelledError

        mocker.patch("asyncio.sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await manager._monitor_loop()

        mock_exec.assert_called_once()
        assert manager.hosts["10.0.0.1"].process is new_proc

    @pytest.mark.asyncio
    async def test_does_not_restart_disabled_worker(self, manager, mocker):
        """Crashed worker with enabled=False must not be restarted."""
        crashed_proc = make_fake_process(pid=100, returncode=1)
        manager.hosts["10.0.0.3"].process = crashed_proc
        manager.hosts["10.0.0.3"].enabled = False

        mock_exec = AsyncMock(return_value=make_fake_process(pid=200))
        mocker.patch("asyncio.create_subprocess_exec", mock_exec)

        sleep_calls = 0

        async def fake_sleep(t):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                raise asyncio.CancelledError

        mocker.patch("asyncio.sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await manager._monitor_loop()

        mock_exec.assert_not_called()
