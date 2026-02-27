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

    def test_diag_field_present_and_all_none_by_default(self, manager):
        """Every status entry must have a 'diag' key with all fields defaulting to None."""
        for item in manager.get_status():
            assert "diag" in item
            diag = item["diag"]
            assert diag["ssh_ok"] is None
            assert diag["shadow_mode"] is None
            assert diag["restrictions_ok"] is None
            assert diag["session_state"] is None
            assert diag["last_checked"] is None

    def test_diag_field_reflects_probe_results(self, manager):
        entry = manager.hosts["10.0.0.1"]
        entry.diag.ssh_ok = True
        entry.diag.shadow_mode = False
        entry.diag.restrictions_ok = False
        entry.diag.session_state = "idle"
        entry.diag.last_checked = 1234567890.0

        item = next(s for s in manager.get_status() if s["host"] == "10.0.0.1")
        diag = item["diag"]
        assert diag["ssh_ok"] is True
        assert diag["shadow_mode"] is False
        assert diag["restrictions_ok"] is False
        assert diag["session_state"] == "idle"
        assert diag["last_checked"] == 1234567890.0


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


# ---------------------------------------------------------------------------
# Config resilience — idempotency against bad config.json
# ---------------------------------------------------------------------------


class TestConfigResilience:
    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "hosts.json"
        path.write_text("{not valid json")
        m = WorkerManager(str(path))
        with pytest.raises(ValueError, match="invalid JSON"):
            m.load_config()

    def test_invalid_json_does_not_mutate_hosts(self, tmp_path):
        """self.hosts must stay untouched if the config file is invalid."""
        good_path = tmp_path / "hosts.json"
        good_path.write_text(json.dumps(BASE_CONFIG))
        m = WorkerManager(str(good_path))
        m.load_config()
        original_hosts = set(m.hosts.keys())

        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{broken")
        m.config_path = str(bad_path)

        with pytest.raises(ValueError):
            m.load_config()

        assert set(m.hosts.keys()) == original_hosts  # unchanged

    def test_missing_host_field_raises(self, tmp_path):
        path = tmp_path / "hosts.json"
        path.write_text(json.dumps({"hosts": [{"login": "x"}]}))  # no "host" key
        m = WorkerManager(str(path))
        with pytest.raises(ValueError, match="missing required 'host' field"):
            m.load_config()

    def test_missing_host_field_does_not_mutate_hosts(self, tmp_path):
        """Partial parse failure must not wipe existing hosts."""
        good_path = tmp_path / "hosts.json"
        good_path.write_text(json.dumps(BASE_CONFIG))
        m = WorkerManager(str(good_path))
        m.load_config()
        original_hosts = set(m.hosts.keys())

        bad_path = tmp_path / "partial.json"
        bad_path.write_text(json.dumps({"hosts": [{"host": "10.0.0.1"}, {"login": "oops"}]}))
        m.config_path = str(bad_path)

        with pytest.raises(ValueError):
            m.load_config()

        assert set(m.hosts.keys()) == original_hosts

    def test_hosts_not_a_list_raises(self, tmp_path):
        path = tmp_path / "hosts.json"
        path.write_text(json.dumps({"hosts": "not-a-list"}))
        m = WorkerManager(str(path))
        with pytest.raises(ValueError, match="must be a list"):
            m.load_config()

    def test_atomic_save_no_temp_file_left_on_success(self, config_file, manager):
        """After a successful save no .tmp file should remain alongside config."""
        import glob
        manager.save_config()
        tmp_files = glob.glob(config_file + "*.tmp") + glob.glob(
            str(config_file).replace(".json", "*.tmp")
        )
        assert tmp_files == []

    def test_save_file_is_valid_json_after_save(self, config_file, manager):
        manager.save_config()
        with open(config_file) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "hosts" in data

    def test_original_file_survives_simulated_write_failure(self, tmp_path):
        """If json.dump raises, the original config.json must be intact."""
        path = tmp_path / "hosts.json"
        original_content = json.dumps(BASE_CONFIG, indent=2)
        path.write_text(original_content)

        m = WorkerManager(str(path))
        m.load_config()

        # Simulate json.dump blowing up (e.g. non-serialisable value injected)
        m.config["__bad__"] = object()  # not JSON-serialisable

        with pytest.raises(TypeError):
            m.save_config()

        # The original file must still be readable and correct
        assert json.loads(path.read_text()) == BASE_CONFIG
