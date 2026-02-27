"""
Tests for drova_web HTTP server — production-readiness checks.

Covers: Basic Auth enforcement, all REST endpoints (CRUD),
correct HTTP status codes, and JSON response shapes.
"""

import base64

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import AsyncMock, MagicMock

from drova_desktop_keenetic.web.manager import WorkerManager
from drova_desktop_keenetic.web.server import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER = "admin"
PASSWORD = "secret"

SAMPLE_STATUS = [
    {"host": "10.0.0.1", "enabled": True, "running": True, "status": "running", "pid": 1234, "exit_code": None},
    {"host": "10.0.0.2", "enabled": False, "running": False, "status": "disabled", "pid": None, "exit_code": None},
]


def auth(user: str = USER, password: str = PASSWORD) -> dict:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def make_mock_manager() -> MagicMock:
    manager = MagicMock(spec=WorkerManager)
    manager.get_status.return_value = list(SAMPLE_STATUS)
    manager.start_worker = AsyncMock()
    manager.stop_worker = AsyncMock()
    manager.add_host = AsyncMock()
    manager.remove_host = AsyncMock()
    return manager


@pytest_asyncio.fixture
async def client():
    manager = make_mock_manager()
    app = create_app(manager, USER, PASSWORD)
    async with TestClient(TestServer(app)) as c:
        # Expose the mock via a plain Python attribute, not via app dict,
        # to avoid aiohttp DeprecationWarning about mutating started app state.
        c._mock_manager = manager  # type: ignore[attr-defined]
        yield c


# ---------------------------------------------------------------------------
# Basic Auth
# ---------------------------------------------------------------------------


class TestBasicAuth:
    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self, client):
        resp = await client.get("/")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, client):
        resp = await client.get("/", headers=auth(password="wrong"))
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_wrong_user_returns_401(self, client):
        resp = await client.get("/", headers=auth(user="hacker"))
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_correct_auth_returns_200(self, client):
        resp = await client.get("/", headers=auth())
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_api_also_requires_auth(self, client):
        resp = await client.get("/api/hosts")
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_401_has_www_authenticate_header(self, client):
        resp = await client.get("/")
        assert "WWW-Authenticate" in resp.headers
        assert "Basic" in resp.headers["WWW-Authenticate"]


# ---------------------------------------------------------------------------
# GET /  (HTML UI)
# ---------------------------------------------------------------------------


class TestIndex:
    @pytest.mark.asyncio
    async def test_returns_html(self, client):
        resp = await client.get("/", headers=auth())
        assert resp.status == 200
        assert "text/html" in resp.content_type
        text = await resp.text()
        assert "<html" in text.lower()


# ---------------------------------------------------------------------------
# GET /api/hosts
# ---------------------------------------------------------------------------


class TestGetHosts:
    @pytest.mark.asyncio
    async def test_returns_list(self, client):
        resp = await client.get("/api/hosts", headers=auth())
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_contains_expected_fields(self, client):
        resp = await client.get("/api/hosts", headers=auth())
        data = await resp.json()
        item = data[0]
        assert "host" in item
        assert "status" in item
        assert "running" in item
        assert "pid" in item

    @pytest.mark.asyncio
    async def test_running_host_shown(self, client):
        resp = await client.get("/api/hosts", headers=auth())
        data = await resp.json()
        hosts_by_ip = {h["host"]: h for h in data}
        assert hosts_by_ip["10.0.0.1"]["status"] == "running"
        assert hosts_by_ip["10.0.0.1"]["running"] is True


# ---------------------------------------------------------------------------
# POST /api/hosts/{host}/start
# ---------------------------------------------------------------------------


class TestStartHost:
    @pytest.mark.asyncio
    async def test_calls_start_worker(self, client):
        manager = client._mock_manager
        resp = await client.post("/api/hosts/10.0.0.1/start", headers=auth())
        assert resp.status == 200
        manager.start_worker.assert_called_once_with("10.0.0.1")

    @pytest.mark.asyncio
    async def test_unknown_host_returns_404(self, client):
        manager = client._mock_manager
        manager.start_worker.side_effect = ValueError("not found")
        resp = await client.post("/api/hosts/9.9.9.9/start", headers=auth())
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_ok_true(self, client):
        resp = await client.post("/api/hosts/10.0.0.1/start", headers=auth())
        data = await resp.json()
        assert data == {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/hosts/{host}/stop
# ---------------------------------------------------------------------------


class TestStopHost:
    @pytest.mark.asyncio
    async def test_calls_stop_worker(self, client):
        manager = client._mock_manager
        resp = await client.post("/api/hosts/10.0.0.1/stop", headers=auth())
        assert resp.status == 200
        manager.stop_worker.assert_called_once_with("10.0.0.1")

    @pytest.mark.asyncio
    async def test_unknown_host_returns_404(self, client):
        manager = client._mock_manager
        manager.stop_worker.side_effect = ValueError("not found")
        resp = await client.post("/api/hosts/9.9.9.9/stop", headers=auth())
        assert resp.status == 404


# ---------------------------------------------------------------------------
# PUT /api/hosts  (add)
# ---------------------------------------------------------------------------


class TestAddHost:
    @pytest.mark.asyncio
    async def test_adds_host(self, client):
        manager = client._mock_manager
        resp = await client.put("/api/hosts", headers=auth(), json={"host": "10.0.0.5"})
        assert resp.status == 200
        manager.add_host.assert_called_once_with(host="10.0.0.5", login=None, password=None)

    @pytest.mark.asyncio
    async def test_passes_login_and_password(self, client):
        manager = client._mock_manager
        await client.put(
            "/api/hosts",
            headers=auth(),
            json={"host": "10.0.0.5", "login": "L", "password": "P"},
        )
        manager.add_host.assert_called_once_with(host="10.0.0.5", login="L", password="P")

    @pytest.mark.asyncio
    async def test_missing_host_field_returns_400(self, client):
        resp = await client.put("/api/hosts", headers=auth(), json={"login": "L"})
        assert resp.status == 400
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_empty_host_returns_400(self, client):
        resp = await client.put("/api/hosts", headers=auth(), json={"host": "  "})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_duplicate_host_returns_409(self, client):
        manager = client._mock_manager
        manager.add_host.side_effect = ValueError("already exists")
        resp = await client.put("/api/hosts", headers=auth(), json={"host": "10.0.0.1"})
        assert resp.status == 409
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_empty_login_becomes_none(self, client):
        """Empty string login must be stored as None, not as empty string."""
        manager = client._mock_manager
        await client.put(
            "/api/hosts",
            headers=auth(),
            json={"host": "10.0.0.5", "login": "", "password": ""},
        )
        manager.add_host.assert_called_once_with(host="10.0.0.5", login=None, password=None)


# ---------------------------------------------------------------------------
# DELETE /api/hosts/{host}
# ---------------------------------------------------------------------------


class TestDeleteHost:
    @pytest.mark.asyncio
    async def test_removes_host(self, client):
        manager = client._mock_manager
        resp = await client.delete("/api/hosts/10.0.0.1", headers=auth())
        assert resp.status == 200
        manager.remove_host.assert_called_once_with("10.0.0.1")

    @pytest.mark.asyncio
    async def test_unknown_host_returns_404(self, client):
        manager = client._mock_manager
        manager.remove_host.side_effect = ValueError("not found")
        resp = await client.delete("/api/hosts/9.9.9.9", headers=auth())
        assert resp.status == 404
        data = await resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_ok_true(self, client):
        resp = await client.delete("/api/hosts/10.0.0.1", headers=auth())
        data = await resp.json()
        assert data == {"ok": True}
