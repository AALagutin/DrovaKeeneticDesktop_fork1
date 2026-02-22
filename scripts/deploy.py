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

    # Check SD status on all hosts (installed? password matches config?):
    ... poetry run python scripts/deploy.py --check-sd

    # Deploy SD installer only where SD is not yet installed:
    ... poetry run python scripts/deploy.py --sd-installer "D:\\Setup\\SD_Setup.exe"
    #  (hosts where SD is already correctly configured are skipped automatically;
    #   hosts with password mismatch are flagged and skipped)
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

SETUP_SCRIPT               = Path(__file__).parent / "setup_gamepc.ps1"
UNINSTALL_SD_SCRIPT        = Path(__file__).parent / "uninstall_sd.ps1"
REMOVE_RESTRICTIONS_SCRIPT = Path(__file__).parent / "remove_restrictions.ps1"
CHECK_SD_SCRIPT            = Path(__file__).parent / "check_sd.ps1"
REMOTE_TEMP_FILENAME = "drova_setup_gamepc.ps1"
# ADMIN$ maps to C:\Windows on remote host
REMOTE_SHARE         = "ADMIN$"
REMOTE_PATH_IN_SHARE = f"Temp\\{REMOTE_TEMP_FILENAME}"
REMOTE_PS1_PATH      = f"C:\\Windows\\Temp\\{REMOTE_TEMP_FILENAME}"

MAX_PARALLEL         = 10
EXEC_TIMEOUT_SECONDS = 600

# Exit codes returned by check_sd.ps1 (parsed in deploy_one).
_SD_OK             = 0   # installed, service running, password OK (or no pwd to verify)
_SD_NOT_INSTALLED  = 2   # SD not installed → safe to run setup with --sd-installer
_SD_NEEDS_ACTION   = 3   # orphaned files, or installed but service not running (reboot)
_SD_WRONG_PASSWORD = 4   # installed + running + password does NOT match config


@dataclass
class HostEntry:
    name: str
    host: str
    login: str
    password: str
    sd_password: str = ""


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
    sd_password = defaults.get("shadow_defender_password", "")
    entries = []
    for i, h in enumerate(data["hosts"]):
        entries.append(HostEntry(
            name=h.get("name", f"PC-{i + 1:02d}"),
            host=h["host"],
            login=h.get("login", login),
            password=h.get("password", password),
            sd_password=h.get("shadow_defender_password", sd_password),
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
            ImpersonationLevel, Open,
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
            0,  # ShareAccess: exclusive (no sharing)
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
# Helpers
# ---------------------------------------------------------------------------

_UTF8_BOM = b"\xef\xbb\xbf"


def _decode_windows_output(data: Optional[bytes]) -> str:
    """Decode pypsexec stdout/stderr: try UTF-8, then CP866 (Russian OEM), then CP1251."""
    if not data:
        return ""
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _ps1_bytes(path: Path) -> bytes:
    """Read a PS1 file and ensure it has a UTF-8 BOM for PowerShell 5.1 compatibility."""
    raw = path.read_bytes()
    return raw if raw.startswith(_UTF8_BOM) else _UTF8_BOM + raw


# ---------------------------------------------------------------------------
# Remote execution via pypsexec
# ---------------------------------------------------------------------------

def _run_ps1(host: str, login: str, password: str, extra_args: str) -> tuple[int, str, str]:
    """Execute the uploaded PS1 on the remote host. Returns (rc, stdout, stderr)."""
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

    out = _decode_windows_output(stdout)
    err = _decode_windows_output(stderr)
    return rc, out, err


def _build_check_args(sd_password: str) -> str:
    """Build argument string for check_sd.ps1."""
    return f'-ShadowDefenderPassword "{sd_password}"' if sd_password else ""


def _build_extra_args(args: argparse.Namespace, sd_password: str = "") -> str:
    """Build argument string for setup_gamepc.ps1."""
    parts = []
    if args.skip_ffmpeg:
        parts.append("-SkipFFmpeg")
    if args.sd_installer:
        parts.append(f'-ShadowDefenderInstaller "{args.sd_installer}"')
    # CLI --sd-password takes precedence over per-host config value
    effective_sd_pwd = args.sd_password or sd_password
    if effective_sd_pwd:
        parts.append(f'-ShadowDefenderPassword "{effective_sd_pwd}"')
    return " ".join(parts)


# ---------------------------------------------------------------------------
# SD pre-check (shared by --check-sd and --sd-installer auto-filter)
# ---------------------------------------------------------------------------

def _run_sd_check(
    host_entry: HostEntry,
    check_ps1_bytes: bytes,
    effective_sd_password: str,
    label: str,
) -> tuple[int, str, str]:
    """Upload check_sd.ps1 and run it. Returns (rc, stdout, stderr)."""
    _upload_ps1(host_entry.host, host_entry.login, host_entry.password, check_ps1_bytes)
    return _run_ps1(
        host_entry.host, host_entry.login, host_entry.password,
        _build_check_args(effective_sd_password),
    )


# ---------------------------------------------------------------------------
# Per-host orchestration
# ---------------------------------------------------------------------------

def deploy_one(
    host_entry: HostEntry,
    ps1_bytes: bytes,
    args: argparse.Namespace,
    check_ps1_bytes: Optional[bytes] = None,
) -> DeployResult:
    label = f"[{host_entry.name} / {host_entry.host}]"
    effective_sd_pwd = args.sd_password or host_entry.sd_password

    # -----------------------------------------------------------------------
    # Mode: --check-sd  (pure SD status report, no setup)
    # -----------------------------------------------------------------------
    if args.check_sd:
        try:
            print(f"{label} Checking SD status...", flush=True)
            _upload_ps1(host_entry.host, host_entry.login, host_entry.password, ps1_bytes)
            rc, out, err = _run_ps1(
                host_entry.host, host_entry.login, host_entry.password,
                _build_check_args(effective_sd_pwd),
            )
        except Exception as exc:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output="", error=f"Check failed: {exc}",
            )
        # exit 4 = wrong password → needs operator attention → [FAIL]
        # exit 3 = needs action (reboot / uninstall-sd) → [FAIL]
        # exit 0 / 2 = informational → [OK]
        success = rc not in (_SD_WRONG_PASSWORD, _SD_NEEDS_ACTION)
        error = ""
        if rc == _SD_WRONG_PASSWORD:
            error = "Password mismatch — update shadow_defender_password in config.json"
        elif rc == _SD_NEEDS_ACTION:
            error = "Needs action — reboot PC or run --uninstall-sd to clear orphaned files"
        return DeployResult(
            name=host_entry.name, host=host_entry.host,
            success=success, output=out.strip(), error=error,
        )

    # -----------------------------------------------------------------------
    # Mode: --uninstall-sd / --remove-restrictions  (one-shot, no pre-check)
    # -----------------------------------------------------------------------
    if args.uninstall_sd:
        action_label, exec_hint = "Uninstalling Shadow Defender", "(SD uninstall + reboot required)"
    elif args.remove_restrictions:
        action_label, exec_hint = "Removing restrictions", "(registry + firewall cleanup)"
    else:
        action_label = "setup script"
        exec_hint    = "(may take 5-10 min: OpenSSH + PsExec + FFmpeg + SD)"

    if args.uninstall_sd or args.remove_restrictions:
        try:
            print(f"{label} Uploading {action_label} via SMB...", flush=True)
            _upload_ps1(host_entry.host, host_entry.login, host_entry.password, ps1_bytes)
        except Exception as exc:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output="", error=f"Upload failed: {exc}",
            )
        try:
            print(f"{label} Executing {exec_hint}...", flush=True)
            rc, out, err = _run_ps1(host_entry.host, host_entry.login, host_entry.password, "")
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=(rc == 0), output=out, error=err,
            )
        except Exception as exc:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output="", error=f"Execution failed: {exc}",
            )

    # -----------------------------------------------------------------------
    # Mode: normal setup (setup_gamepc.ps1)
    # Optional SD pre-check when --sd-installer is provided.
    # -----------------------------------------------------------------------
    if check_ps1_bytes is not None and args.sd_installer:
        try:
            print(f"{label} Pre-checking SD status...", flush=True)
            rc, out, err = _run_sd_check(
                host_entry, check_ps1_bytes, effective_sd_pwd, label,
            )
        except Exception as exc:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output="", error=f"SD pre-check failed: {exc}",
            )

        if rc == _SD_OK:
            # SD already correctly configured — skip setup for this host
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=True,
                output=out.strip() + "\n  → SD already configured, setup skipped.",
                error="",
            )
        if rc == _SD_WRONG_PASSWORD:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output=out.strip(),
                error=(
                    "SD password mismatch — update shadow_defender_password in config.json "
                    "before deploying the installer."
                ),
            )
        if rc == _SD_NEEDS_ACTION:
            return DeployResult(
                name=host_entry.name, host=host_entry.host,
                success=False, output=out.strip(),
                error=(
                    "SD installed but not operational — reboot PC first, "
                    "or run --uninstall-sd to clear orphaned files."
                ),
            )
        # rc == _SD_NOT_INSTALLED: SD absent → proceed with setup below

    extra_args = _build_extra_args(args, host_entry.sd_password)
    try:
        print(f"{label} Uploading {action_label} via SMB...", flush=True)
        _upload_ps1(host_entry.host, host_entry.login, host_entry.password, ps1_bytes)
    except Exception as exc:
        return DeployResult(
            name=host_entry.name, host=host_entry.host,
            success=False, output="", error=f"Upload failed: {exc}",
        )
    try:
        print(f"{label} Executing {exec_hint}...", flush=True)
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
        "--check-sd", action="store_true",
        help=(
            "Report Shadow Defender status for every host: installed/not-installed, "
            "service state, and whether the password in config.json matches. "
            "No changes are made to any machine."
        ),
    )
    p.add_argument(
        "--uninstall-sd", action="store_true",
        help="Deploy uninstall_sd.ps1 instead of setup_gamepc.ps1 to silently remove Shadow Defender.",
    )
    p.add_argument(
        "--remove-restrictions", action="store_true",
        help=(
            "Deploy remove_restrictions.ps1 to undo all registry and firewall restrictions "
            "left behind after a force-killed Drova client session."
        ),
    )
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
            "Hosts where SD is already correctly configured are skipped automatically. "
            "Hosts with a password mismatch are flagged and skipped."
        ),
    )
    p.add_argument(
        "--sd-password",
        metavar="PWD",
        default="",
        help=(
            "Shadow Defender password to verify with CmdTool.exe. "
            "Leave empty for fresh installs (no password configured yet). "
            "Overrides per-host shadow_defender_password from config.json."
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


def main() -> None:
    args = parse_args()

    # Select the main script to upload
    if args.check_sd:
        script = CHECK_SD_SCRIPT
    elif args.uninstall_sd:
        script = UNINSTALL_SD_SCRIPT
    elif args.remove_restrictions:
        script = REMOVE_RESTRICTIONS_SCRIPT
    else:
        script = SETUP_SCRIPT

    if not script.exists():
        print(f"ERROR: {script} not found.", file=sys.stderr)
        sys.exit(1)

    ps1_bytes = _ps1_bytes(script)
    filter_ips = [ip.strip() for ip in args.hosts.split(",")] if args.hosts else None
    hosts = load_hosts(filter_ips)

    # Load check_sd.ps1 when we need the SD pre-check before --sd-installer
    check_ps1_bytes: Optional[bytes] = None
    if args.sd_installer and not args.check_sd:
        if not CHECK_SD_SCRIPT.exists():
            print(f"ERROR: {CHECK_SD_SCRIPT} not found.", file=sys.stderr)
            sys.exit(1)
        check_ps1_bytes = _ps1_bytes(CHECK_SD_SCRIPT)

    if args.check_sd:
        print(f"\nChecking SD status on {len(hosts)} host(s) with parallelism={args.parallel}")
    else:
        print(f"\nDeploying to {len(hosts)} host(s) with parallelism={args.parallel}")
    print("=" * 60)

    results: list[DeployResult] = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(deploy_one, h, ps1_bytes, args, check_ps1_bytes): h
            for h in hosts
        }
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
    if args.check_sd:
        action_summary = "checked successfully"
    elif args.uninstall_sd:
        action_summary = "uninstalled Shadow Defender on"
    elif args.remove_restrictions:
        action_summary = "removed restrictions on"
    else:
        action_summary = "set up"
    print(f"  {color_on}{ok_count}/{total} hosts {action_summary}.{color_off}")
    print()
    if ok_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
