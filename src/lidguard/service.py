from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import data_dir

SERVICE_NAME = "lid-guard"
LAUNCHD_LABEL = "io.github.jasonlevigoodison.lid-guard"


def service_file() -> Path:
    if sys.platform == "linux":
        return _systemd_service_file()
    if sys.platform == "darwin":
        return _launchd_service_file()
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def service_installed() -> bool:
    try:
        return service_file().exists()
    except RuntimeError:
        return False


def install_service(enable: bool = True) -> Path:
    wrapper = _write_wrapper_script()
    if sys.platform == "linux":
        service_file = _systemd_service_file()
        _write_text_file(service_file, _systemd_unit_contents(wrapper))
        if enable:
            _run_checked(["systemctl", "--user", "daemon-reload"])
            _run_checked(["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"])
        return service_file

    if sys.platform == "darwin":
        service_file = _launchd_service_file()
        _write_text_file(service_file, _launchd_plist_contents(wrapper))
        if enable:
            domain = f"gui/{os.getuid()}"
            subprocess.run(
                ["launchctl", "bootout", domain, str(service_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            _run_checked(["launchctl", "bootstrap", domain, str(service_file)])
            _run_checked(["launchctl", "kickstart", "-k", f"{domain}/{LAUNCHD_LABEL}"])
        return service_file

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def uninstall_service(disable: bool = True) -> list[Path]:
    removed: list[Path] = []

    if sys.platform == "linux":
        service_file = _systemd_service_file()
        if disable:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"],
                capture_output=True,
                text=True,
                check=False,
            )
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True,
                text=True,
                check=False,
            )
        removed.extend(_remove_known_files(service_file, _wrapper_path()))
        return removed

    if sys.platform == "darwin":
        service_file = _launchd_service_file()
        if disable:
            domain = f"gui/{os.getuid()}"
            subprocess.run(
                ["launchctl", "bootout", domain, str(service_file)],
                capture_output=True,
                text=True,
                check=False,
            )
        removed.extend(_remove_known_files(service_file, _wrapper_path()))
        return removed

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _systemd_service_file() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"


def _launchd_service_file() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _wrapper_path() -> Path:
    return data_dir() / "service" / "run-service"


def _write_wrapper_script() -> Path:
    path = _wrapper_path()
    command, pythonpath = _launch_command()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/usr/bin/env sh",
        "set -eu",
    ]
    if pythonpath:
        lines.append(f'export PYTHONPATH="{pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}"')
    lines.append(f'exec {shlex.join(command)} "$@"')
    _write_text_file(path, "\n".join(lines) + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _launch_command() -> tuple[list[str], str | None]:
    entrypoint = Path(sys.argv[0]).resolve()
    if entrypoint.exists() and (entrypoint.suffix == ".pyz" or entrypoint.name == SERVICE_NAME):
        return [sys.executable, str(entrypoint), "run"], None
    return [sys.executable, "-m", "lidguard", "run"], _source_pythonpath()


def _source_pythonpath() -> str | None:
    package_root = Path(__file__).resolve().parents[1]
    if package_root.name == "src":
        return str(package_root)
    return None


def _systemd_unit_contents(wrapper: Path) -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=lid-guard",
            "After=graphical-session.target",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={wrapper}",
            "Restart=on-failure",
            "RestartSec=5",
            "Environment=PYTHONUNBUFFERED=1",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def _launchd_plist_contents(wrapper: Path) -> str:
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
            '<plist version="1.0">',
            "<dict>",
            f"  <key>Label</key><string>{LAUNCHD_LABEL}</string>",
            "  <key>ProgramArguments</key>",
            "  <array>",
            f"    <string>{wrapper}</string>",
            "  </array>",
            "  <key>RunAtLoad</key><true/>",
            "  <key>KeepAlive</key><true/>",
            "  <key>StandardOutPath</key>",
            f"  <string>{data_dir() / 'service' / 'stdout.log'}</string>",
            "  <key>StandardErrorPath</key>",
            f"  <string>{data_dir() / 'service' / 'stderr.log'}</string>",
            "</dict>",
            "</plist>",
            "",
        ]
    )


def _write_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.name,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(contents)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _run_checked(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        message = stderr or stdout or f"{command[0]} exited with status {result.returncode}"
        raise RuntimeError(message)


def _remove_known_files(*paths: Path) -> list[Path]:
    removed: list[Path] = []
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    return removed
