#!/usr/bin/env python3
"""
deploy.py — Push setup_gamepc.ps1 to all GamePCs and run it.

Prerequisites on each target Windows machine:
  - LocalAccountTokenFilterPolicy = 1  (already done)
  - Network profile = Private           (already done)
  - SMB port 445 reachable from this Linux machine

Usage:
    # Using config.json:
    DROVA_CONFIG=/opt/drova-desktop/config.json poetry run python scripts/deploy.py

    # Using environment variables (single or multi-host):
    WINDOWS_HOSTS=192.168.0.10,192.168.0.11 WINDOWS_LOGIN=Administrator \\
        WINDOWS_PASSWORD=secret poetry run python scripts/deploy.py

    # Skip FFmpeg installation:
    ... poetry run python scripts/deploy.py --skip-ffmpeg

    # Target specific hosts only:
    ... poetry run python scripts/deploy.py --hosts 192.168.0.10,192.168.0.11
"""

import argparse
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SETUP_SCRIPT = Path(__file__).parent / "setup_gamepc.ps1"
REMOTE_TEMP_FILENAME = "drova_setup_gamepc.ps1"
# ADMIN$ maps to C:\Windows on remote host
REMOTE_SHARE = "ADMIN$"
REMOTE_PATH_IN_SHARE = f"Temp\\{REMOTE_TEMP_FILENAME}"
REMOTE_PS1_PATH = f"C:\\Windows\\Temp\\{REMOTE_TEMP_FILENAME}"

MAX_PARALLEL = 10
EXEC_TIMEOUT_SECONDS = 600


@dataclass
class HostEntry:
    name: str
    host: str
    login: str
    password: str


@dataclass
class DeployResult:
    name: str
    host: str
    success: bool
    output: str
    error: str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_hosts(filter_ips: Optional[list[str]] = None) -> list[HostEntry]:
    config_path = os.environ.get("DROVA_CONFIG")
    if config_path and Path(config_path).exists():
        hosts = _hosts_from_json(config_path)
    else:
        hosts = _hosts_from_env()

    if filter_ips:
        hosts = [h for h in hosts if h.host in filter_ips]

    if not hosts:
        print("ERROR: No hosts found. Check DROVA_CONFIG / WINDOWS_HOST(S) / --hosts.", file=sys.stderr)
        sys.exit(1)

    return hosts


def _hosts_from_json(path: str) -> list[HostEntry]:
    with open(path) as f:
        data = json.load(f)
    defaults = data.get("defaults", {})
    login = defaults.get("login", os.environ.get("WINDOWS_LOGIN", ""))
    password = defaults.get("password", os.environ.get("WINDOWS_PASSWORD", ""))
    entries = []
    for i, h in enumerate(data["hosts"]):
        entries.append(HostEntry(
            name=h.get("name", f"PC-{i + 1:02d}"),
            host=h["host"],
            login=h.get("login", login),
            password=h.get("password", password),
        ))
    return entries


def _hosts_from_env() -> list[HostEntry]:
    login = os.environ.get("WINDOWS_LOGIN", "")
    password = os.environ.get("WINDOWS_PASSWORD", "")
    hosts_str = os.environ.get("WINDOWS_HOSTS") or os.environ.get("WINDOWS_HOST", "")
    ips = [ip.strip() for ip in hosts_str.split(",") if ip.strip()]
    return [
        HostEntry(name=f"PC-{i + 1:02d}", host=ip, login=login, password=password)
        for i, ip in enumerate(ips)
    ]


# ---------------------------------------------------------------------------
# SMB file upload
# ---------------------------------------------------------------------------

def _upload_ps1(host: str, login: str, password: str, content: bytes) -> None:
    r"""Write content to \\host\ADMIN$\Temp\drova_setup_gamepc.ps1 via SMB."""
    try:
        from smbprotocol.connection import Connection
        from smbprotocol.open import (
            CreateDisposition, CreateOptions, FileAttributes,
            ImpersonationLevel, Open, ShareAccess,
        )
        from smbprotocol.session import Session
        from smbprotocol.tree import TreeConnect
    except ImportError:
        raise RuntimeError(
            "smbprotocol not installed. Run: poetry install --with setup"
        )

    conn = Connection(uuid.uuid4(), host, 445)
    conn.connect()
    try:
        session = Session(conn, username=login, password=password, require_encryption=False)
        session.connect()
        tree = TreeConnect(session, rf"\\{host}\{REMOTE_SHARE}")
        tree.connect()

        file_open = Open(tree, REMOTE_PATH_IN_SHARE)
        file_open.create(
            ImpersonationLevel.Impersonation,
            0x40000000,                              # GENERIC_WRITE
            FileAttributes.FILE_ATTRIBUTE_NORMAL,
            ShareAccess.SHARE_NONE,
            CreateDisposition.FILE_OVERWRITE_IF,
            CreateOptions.FILE_NON_DIRECTORY_FILE,
        )
        file_open.write(content, 0)
        file_open.close(False)

        tree.disconnect()
        session.disconnect()
    finally:
        conn.disconnect()


# ---------------------------------------------------------------------------
# Remote execution via pypsexec
# ---------------------------------------------------------------------------

def _run_ps1(host: str, login: str, password: str, extra_args: str) -> tuple[int, str, str]:
    """Execute setup_gamepc.ps1 on the remote host. Returns (rc, stdout, stderr)."""
    try:
        from pypsexec.client import Client
    except ImportError:
        raise RuntimeError(
            "pypsexec not installed. Run: poetry install --with setup"
        )

    args = f"-NoProfile -ExecutionPolicy Bypass -File {REMOTE_PS1_PATH}"
    if extra_args:
        args += f" {extra_args}"

    client = Client(host, username=login, password=password)
    client.connect()
    try:
        client.create_service()
        stdout, stderr, rc = client.run_executable(
            "powershell.exe",
            arguments=args,
            timeout_seconds=EXEC_TIMEOUT_SECONDS,
        )
    finally:
        try:
            client.remove_service()
        except Exception:
            pass
        client.disconnect()

    out = stdout.decode("utf-8", errors="replace") if stdout else ""
    err = stderr.decode("utf-8", errors="replace") if stderr else ""
    return rc, out, err


# ---------------------------------------------------------------------------
# Per-host orchestration
# ---------------------------------------------------------------------------

def deploy_one(host_entry: HostEntry, ps1_bytes: bytes, extra_args: str) -> DeployResult:
    label = f"[{host_entry.name} / {host_entry.host}]"
    try:
        print(f"{label} Uploading setup script via SMB...", flush=True)
        _upload_ps1(host_entry.host, host_entry.login, host_entry.password, ps1_bytes)
    except Exception as exc:
        return DeployResult(
            name=host_entry.name, host=host_entry.host,
            success=False, output="", error=f"Upload failed: {exc}",
        )

    try:
        print(f"{label} Executing (may take 5-10 min: OpenSSH + PsExec + FFmpeg + SD)...", flush=True)
        rc, out, err = _run_ps1(host_entry.host, host_entry.login, host_entry.password, extra_args)
        return DeployResult(
            name=host_entry.name, host=host_entry.host,
            success=(rc == 0), output=out, error=err,
        )
    except Exception as exc:
        return DeployResult(
            name=host_entry.name, host=host_entry.host,
            success=False, output="", error=f"Execution failed: {exc}",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deploy Drova GamePC setup to all hosts.")
    p.add_argument(
        "--skip-ffmpeg", action="store_true",
        help="Pass -SkipFFmpeg to setup_gamepc.ps1 (faster, no streaming support)",
    )
    p.add_argument(
        "--sd-installer",
        metavar="PATH",
        help=(
            "Path to Shadow Defender installer on the REMOTE Windows machine "
            "(e.g. D:\\Setup\\ShadowDefender_Setup.exe). "
            "If omitted, script detects SD and reports status but does not install it."
        ),
    )
    p.add_argument(
        "--sd-password",
        metavar="PWD",
        default="",
        help=(
            "Shadow Defender password to verify with CmdTool.exe. "
            "Leave empty for fresh installs (no password configured yet)."
        ),
    )
    p.add_argument(
        "--hosts",
        help="Comma-separated list of IP addresses to target (overrides config host list)",
    )
    p.add_argument(
        "--parallel", type=int, default=MAX_PARALLEL,
        help=f"Max simultaneous deployments (default: {MAX_PARALLEL})",
    )
    return p.parse_args()


def _build_extra_args(args: argparse.Namespace) -> str:
    parts = []
    if args.skip_ffmpeg:
        parts.append("-SkipFFmpeg")
    if args.sd_installer:
        parts.append(f'-ShadowDefenderInstaller "{args.sd_installer}"')
    if args.sd_password:
        parts.append(f'-ShadowDefenderPassword "{args.sd_password}"')
    return " ".join(parts)


def main() -> None:
    args = parse_args()

    if not SETUP_SCRIPT.exists():
        print(f"ERROR: {SETUP_SCRIPT} not found.", file=sys.stderr)
        sys.exit(1)

    ps1_bytes = SETUP_SCRIPT.read_bytes()
    filter_ips = [ip.strip() for ip in args.hosts.split(",")] if args.hosts else None
    hosts = load_hosts(filter_ips)
    extra_args = _build_extra_args(args)

    print(f"\nDeploying to {len(hosts)} host(s) with parallelism={args.parallel}")
    print("=" * 60)

    results: list[DeployResult] = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(deploy_one, h, ps1_bytes, extra_args): h for h in hosts}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Final summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    ok_count = 0
    for r in sorted(results, key=lambda x: x.host):
        status = "OK  " if r.success else "FAIL"
        color_on  = "\033[32m" if r.success else "\033[31m"
        color_off = "\033[0m"
        print(f"  {color_on}[{status}]{color_off}  {r.name:12s}  {r.host}")
        if r.output:
            for line in r.output.strip().splitlines():
                print(f"          {line}")
        if r.error:
            print(f"         \033[31mERROR: {r.error.strip()}\033[0m")
        if r.success:
            ok_count += 1

    print()
    total = len(results)
    color_on  = "\033[32m" if ok_count == total else "\033[31m"
    color_off = "\033[0m"
    print(f"  {color_on}{ok_count}/{total} hosts set up successfully.{color_off}")
    print()
    if ok_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
