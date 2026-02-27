"""
OBS WebSocket v5 client (OBS 28+).

Provides a minimal async client for controlling OBS recording over the built-in
WebSocket server (Tools → WebSocket Server Settings in OBS).

The helpers obs_start_recording() and obs_stop_recording() open an SSH port-forward
tunnel from the Linux gate to the Windows PC, connect to OBS, and issue the
appropriate command.  The recording file must be written to a network share (SMB)
that is pre-mapped in the etalon image; local paths will be destroyed by Shadow
Defender on reboot.

Protocol reference: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from typing import Any

import aiohttp
from asyncssh import SSHClientConnection

logger = logging.getLogger(__name__)

# OBS WebSocket v5 op-codes
_OP_HELLO = 0
_OP_IDENTIFY = 1
_OP_IDENTIFIED = 2
_OP_REQUEST = 6
_OP_REQUEST_RESPONSE = 7


class OBSWebSocketError(RuntimeError):
    """Raised when OBS WebSocket reports an error or times out."""


class OBSWebSocket:
    """
    Minimal async context-manager client for OBS WebSocket protocol v5.

    Usage::

        async with OBSWebSocket("ws://127.0.0.1:4455", password="secret") as obs:
            await obs.start_record()
            ...
            path = await obs.stop_record()
    """

    def __init__(self, url: str, password: str | None = None) -> None:
        self.url = url
        self.password = password
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def __aenter__(self) -> "OBSWebSocket":
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(self.url)
            await self._handshake()
        except Exception:
            await self._session.close()
            raise
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _recv(self, timeout: float = 10.0) -> dict:
        msg = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
        if msg.type == aiohttp.WSMsgType.TEXT:
            return json.loads(msg.data)
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
            raise OBSWebSocketError(f"WebSocket closed unexpectedly: {msg.extra}")
        raise OBSWebSocketError(f"Unexpected WebSocket message type: {msg.type}")

    async def _handshake(self) -> None:
        # Step 1: receive Hello
        hello = await self._recv(timeout=10.0)
        if hello["op"] != _OP_HELLO:
            raise OBSWebSocketError(f"Expected Hello (op=0), got op={hello['op']}")

        # Step 2: build Identify (with optional authentication)
        identify: dict = {"rpcVersion": 1, "eventSubscriptions": 0}
        if "authentication" in hello["d"] and self.password:
            salt = hello["d"]["authentication"]["salt"]
            challenge = hello["d"]["authentication"]["challenge"]
            secret = base64.b64encode(
                hashlib.sha256((self.password + salt).encode("utf-8")).digest()
            ).decode("utf-8")
            auth = base64.b64encode(
                hashlib.sha256((secret + challenge).encode("utf-8")).digest()
            ).decode("utf-8")
            identify["authentication"] = auth

        await self._ws.send_json({"op": _OP_IDENTIFY, "d": identify})

        # Step 3: wait for Identified
        identified = await self._recv(timeout=10.0)
        if identified["op"] != _OP_IDENTIFIED:
            raise OBSWebSocketError(f"Expected Identified (op=2), got op={identified['op']}")

        logger.debug("OBS WebSocket handshake complete (rpcVersion=%s)", identified["d"].get("negotiatedRpcVersion"))

    async def _request(
        self,
        request_type: str,
        request_data: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Send a Request (op=6) and return the responseData from the matching RequestResponse (op=7)."""
        req_id = str(uuid.uuid4())
        payload: dict = {"op": _OP_REQUEST, "d": {"requestType": request_type, "requestId": req_id}}
        if request_data:
            payload["d"]["requestData"] = request_data

        await self._ws.send_json(payload)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise OBSWebSocketError(f"Timeout waiting for {request_type} response ({timeout}s)")
            resp = await self._recv(timeout=remaining)
            # Skip Events (op=5) and anything else that isn't our response
            if resp["op"] == _OP_REQUEST_RESPONSE and resp["d"]["requestId"] == req_id:
                status = resp["d"]["requestStatus"]
                if not status["result"]:
                    raise OBSWebSocketError(
                        f"{request_type} failed: code={status['code']} comment={status.get('comment', '')}"
                    )
                return resp["d"].get("responseData") or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_record(self) -> None:
        """Start OBS recording.  Raises OBSWebSocketError if already recording or on failure."""
        await self._request("StartRecord")
        logger.info("OBS: StartRecord acknowledged")

    async def stop_record(self) -> str:
        """Stop OBS recording.  Returns the output file path reported by OBS."""
        data = await self._request("StopRecord", timeout=30.0)
        path: str = data.get("outputPath", "")
        logger.info("OBS: recording stopped, outputPath=%s", path)
        return path

    async def get_record_status(self) -> bool:
        """Return True if OBS is currently recording."""
        data = await self._request("GetRecordStatus")
        return bool(data.get("outputActive"))


# ---------------------------------------------------------------------------
# High-level helpers used by BeforeConnect / AfterDisconnect
# ---------------------------------------------------------------------------


async def obs_start_recording(
    client: SSHClientConnection,
    ws_port: int = 4455,
    ws_password: str | None = None,
    timeout: float = 90.0,
) -> None:
    """
    Forward OBS WebSocket port over SSH, connect, start recording, and verify.

    Polls until OBS responds (handles the delay while OBS initialises after launch).
    Raises OBSWebSocketError if recording cannot be confirmed within *timeout* seconds.
    """
    logger.info("obs_start_recording: opening SSH tunnel → Windows::%d", ws_port)
    async with client.forward_local_port("127.0.0.1", 0, "127.0.0.1", ws_port) as fwd:
        local_port = fwd.get_port()
        url = f"ws://127.0.0.1:{local_port}"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            try:
                async with OBSWebSocket(url, ws_password) as obs:
                    await obs.start_record()
                    # Brief pause so OBS can actually open the output file
                    await asyncio.sleep(2)
                    if await obs.get_record_status():
                        logger.info("obs_start_recording: recording confirmed active")
                        return
                    logger.warning("obs_start_recording: StartRecord sent but outputActive=False, retrying")
            except (aiohttp.ClientConnectionError, OSError, asyncio.TimeoutError, OBSWebSocketError) as exc:
                logger.debug("obs_start_recording: OBS not ready yet (%s), retrying in 2s", exc)
                await asyncio.sleep(2)

        raise OBSWebSocketError(f"OBS recording did not start within {timeout:.0f}s")


async def obs_stop_recording(
    client: SSHClientConnection,
    ws_port: int = 4455,
    ws_password: str | None = None,
) -> str:
    """
    Forward OBS WebSocket port over SSH, connect, and stop recording.

    Returns the output file path reported by OBS, or an empty string on error.
    Does *not* raise — a failed stop should not prevent the reboot.
    """
    logger.info("obs_stop_recording: opening SSH tunnel → Windows::%d", ws_port)
    try:
        async with client.forward_local_port("127.0.0.1", 0, "127.0.0.1", ws_port) as fwd:
            local_port = fwd.get_port()
            url = f"ws://127.0.0.1:{local_port}"
            async with OBSWebSocket(url, ws_password) as obs:
                return await obs.stop_record()
    except Exception as exc:
        logger.error("obs_stop_recording: failed to stop gracefully: %s", exc)
        return ""
