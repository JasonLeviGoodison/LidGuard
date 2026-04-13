from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import active_config_file, data_dir, load_config
from .process_watcher import probe_process_listing
from .service import service_file, service_installed


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix_hint: str = ""


def collect_checks(config: dict | None = None) -> list[CheckResult]:
    current = config if config is not None else load_config()
    checks = [
        _config_parent_check(),
        _data_dir_parent_check(),
        _process_listing_check(),
    ]

    if os.sys.platform == "linux":
        from .platform_linux import LOCK_COMMANDS, read_lid_state

        checks.extend(
            [
                CheckResult(
                    name="Lid state access",
                    ok=read_lid_state() is not None,
                    detail="Read /proc/acpi/button/lid state."
                    if read_lid_state() is not None
                    else "Could not read /proc/acpi/button/lid state.",
                    fix_hint="Confirm your kernel exposes lid state in /proc/acpi/button/lid."
                    if read_lid_state() is None
                    else "",
                ),
                CheckResult(
                    name="D-Bus inhibitor",
                    ok=_module_available("dbus"),
                    detail="python3-dbus is importable."
                    if _module_available("dbus")
                    else "python3-dbus is not installed.",
                    fix_hint="Install python3-dbus so lid-guard can talk to logind."
                    if not _module_available("dbus")
                    else "",
                ),
                CheckResult(
                    name="Screen locker",
                    ok=any(shutil.which(command[0]) for command in LOCK_COMMANDS),
                    detail="At least one supported screen locker is installed."
                    if any(shutil.which(command[0]) for command in LOCK_COMMANDS)
                    else "No supported screen locker was found in PATH.",
                    fix_hint="Install loginctl, xdg-screensaver, swaylock, i3lock, or another supported locker."
                    if not any(shutil.which(command[0]) for command in LOCK_COMMANDS)
                    else "",
                ),
                CheckResult(
                    name="systemctl",
                    ok=shutil.which("systemctl") is not None,
                    detail="systemctl is available for user-service install."
                    if shutil.which("systemctl") is not None
                    else "systemctl is not available.",
                    fix_hint="Use a systemd-based Linux session if you want service management."
                    if shutil.which("systemctl") is None
                    else "",
                ),
                CheckResult(
                    name="Background service",
                    ok=service_installed(),
                    detail=f"Installed at {service_file()}."
                    if service_installed()
                    else "User service is not installed.",
                    fix_hint="Run: lid-guard service install" if not service_installed() else "",
                ),
            ]
        )
    elif os.sys.platform == "darwin":
        from .platform_macos import read_lid_state

        hotspot_enabled = bool(current.get("hotspot", {}).get("enabled"))
        checks.extend(
            [
                _command_check("caffeinate", "caffeinate"),
                _command_check("ioreg", "ioreg"),
                _command_check("osascript", "osascript"),
                _command_check("launchctl", "launchctl"),
                CheckResult(
                    name="Hotspot tooling",
                    ok=not hotspot_enabled or shutil.which("networksetup") is not None,
                    detail="networksetup is available."
                    if shutil.which("networksetup") is not None
                    else "networksetup is not available.",
                    fix_hint="Hotspot auto-connect needs networksetup."
                    if hotspot_enabled and shutil.which("networksetup") is None
                    else "",
                ),
                CheckResult(
                    name="Lid state access",
                    ok=read_lid_state() is not None,
                    detail="Read AppleClamshellState from ioreg."
                    if read_lid_state() is not None
                    else "Could not read AppleClamshellState from ioreg.",
                    fix_hint="Check that ioreg is allowed and available on this Mac."
                    if read_lid_state() is None
                    else "",
                ),
                CheckResult(
                    name="Background service",
                    ok=service_installed(),
                    detail=f"Installed at {service_file()}."
                    if service_installed()
                    else "LaunchAgent is not installed.",
                    fix_hint="Run: lid-guard service install" if not service_installed() else "",
                ),
            ]
        )
    else:
        checks.append(
            CheckResult(
                name="Platform support",
                ok=False,
                detail=f"Unsupported platform: {os.sys.platform}",
                fix_hint="lid-guard currently supports macOS and Linux only.",
            )
        )

    return checks


def render_report() -> tuple[int, str]:
    config = load_config()
    checks = collect_checks(config)
    failing = [check for check in checks if not check.ok]
    lines = [
        "lid-guard doctor",
        "",
        f"Config file: {active_config_file()}",
        f"Data dir:    {data_dir()}",
        f"Processes:   {', '.join(config['watched_processes'])}",
    ]
    if os.sys.platform == "darwin":
        hotspot = config["hotspot"]
        if hotspot["enabled"] and hotspot["ssid"]:
            hotspot_status = hotspot["ssid"]
            if hotspot.get("force_on_network_loss", True):
                hotspot_status += " (failover enabled)"
        else:
            hotspot_status = "disabled"
        lines.append(f"Hotspot:     {hotspot_status}")
    lines.append("")

    for check in checks:
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {check.detail}")
        if check.fix_hint:
            lines.append(f"       Fix: {check.fix_hint}")

    exit_code = 0 if not failing else 1
    return exit_code, "\n".join(lines) + "\n"


def _config_parent_check() -> CheckResult:
    path = active_config_file()
    parent = _nearest_existing_parent(path.parent)
    writable = os.access(parent, os.W_OK)
    return CheckResult(
        name="Config directory",
        ok=writable,
        detail=f"{parent} is writable." if writable else f"{parent} is not writable.",
        fix_hint="Adjust directory permissions or set LID_GUARD_CONFIG_HOME."
        if not writable
        else "",
    )


def _data_dir_parent_check() -> CheckResult:
    path = data_dir()
    parent = _nearest_existing_parent(path)
    writable = os.access(parent, os.W_OK)
    return CheckResult(
        name="Data directory",
        ok=writable,
        detail=f"{parent} is writable." if writable else f"{parent} is not writable.",
        fix_hint="Adjust directory permissions or set LID_GUARD_DATA_HOME."
        if not writable
        else "",
    )


def _process_listing_check() -> CheckResult:
    ok, detail = probe_process_listing()
    return CheckResult(
        name="Process enumeration",
        ok=ok,
        detail=detail,
        fix_hint="Confirm ps works, or run lid-guard on a system that exposes /proc."
        if not ok
        else "",
    )


def _command_check(name: str, command: str) -> CheckResult:
    present = shutil.which(command) is not None
    return CheckResult(
        name=name,
        ok=present,
        detail=f"{command} is available." if present else f"{command} is not available.",
        fix_hint=f"Install or restore {command} in PATH." if not present else "",
    )


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except Exception:
        return False
    return True


def _nearest_existing_parent(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current
