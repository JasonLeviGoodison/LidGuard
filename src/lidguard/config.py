from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import APP_NAME

log = logging.getLogger("lidguard.config")

DEFAULT_WATCHED_PROCESSES = ["claude", "codex", "openclaw"]
DEFAULT_CONFIG = {
    "watched_processes": DEFAULT_WATCHED_PROCESSES,
    "process_poll_interval_seconds": 2.0,
    "lid_poll_interval_seconds": 0.3,
    "hotspot": {
        "enabled": False,
        "ssid": "",
        "force_on_network_loss": True,
        "network_check_interval_seconds": 2.0,
        "reconnect_interval_seconds": 5.0,
        "internet_check_enabled": True,
        "internet_check_url": "https://captive.apple.com/hotspot-detect.html",
        "internet_check_match": "Success",
        "internet_check_timeout_seconds": 2.5,
        "internet_check_failures_before_force": 2,
    },
}


def config_dir() -> Path:
    override = os.environ.get("LID_GUARD_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".config" / APP_NAME


def data_dir() -> Path:
    override = os.environ.get("LID_GUARD_DATA_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def legacy_config_file() -> Path | None:
    if os.environ.get("LID_GUARD_CONFIG_HOME") or sys.platform != "darwin":
        return None
    return Path.home() / ".config" / APP_NAME / "config.json"


def config_file_candidates() -> tuple[Path, ...]:
    primary = config_file()
    legacy = legacy_config_file()
    if legacy is None or legacy == primary:
        return (primary,)
    return (primary, legacy)


def existing_config_file() -> Path | None:
    for path in config_file_candidates():
        if path.exists():
            return path
    return None


def active_config_file() -> Path:
    return existing_config_file() or config_file()


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def load_config() -> dict[str, Any]:
    path = existing_config_file()
    if path is None:
        return default_config()

    legacy = legacy_config_file()
    if legacy is not None and path == legacy:
        log.info("Loaded legacy macOS config from %s.", path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read %s: %s. Using defaults.", path, exc)
        return default_config()

    try:
        return normalize_config(raw)
    except ValueError as exc:
        log.warning("Invalid config in %s: %s. Using defaults.", path, exc)
        return default_config()


def save_config(config: dict[str, Any]) -> Path:
    normalized = normalize_config(config)
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=path.name,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as handle:
        json.dump(normalized, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)

    temp_path.replace(path)
    log.debug("Saved config to %s", path)
    return path


def normalize_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")

    config = default_config()

    watched = raw.get("watched_processes")
    if watched is not None:
        if not isinstance(watched, list):
            raise ValueError("'watched_processes' must be a list")
        normalized = [name for name in (_normalize_process_name(item) for item in watched) if name]
        if normalized:
            config["watched_processes"] = normalized

    process_interval = raw.get("process_poll_interval_seconds")
    if process_interval is not None:
        config["process_poll_interval_seconds"] = _positive_float(
            process_interval,
            "process_poll_interval_seconds",
        )

    lid_interval = raw.get("lid_poll_interval_seconds")
    if lid_interval is not None:
        config["lid_poll_interval_seconds"] = _positive_float(
            lid_interval,
            "lid_poll_interval_seconds",
        )

    hotspot = raw.get("hotspot")
    if hotspot is not None:
        if not isinstance(hotspot, dict):
            raise ValueError("'hotspot' must be an object")
        enabled = hotspot.get("enabled", config["hotspot"]["enabled"])
        if not isinstance(enabled, bool):
            raise ValueError("'hotspot.enabled' must be true or false")
        ssid = hotspot.get("ssid", config["hotspot"]["ssid"])
        if not isinstance(ssid, str):
            raise ValueError("'hotspot.ssid' must be a string")
        force_on_network_loss = hotspot.get(
            "force_on_network_loss",
            config["hotspot"]["force_on_network_loss"],
        )
        if not isinstance(force_on_network_loss, bool):
            raise ValueError("'hotspot.force_on_network_loss' must be true or false")
        network_check_interval_seconds = _positive_float(
            hotspot.get(
                "network_check_interval_seconds",
                config["hotspot"]["network_check_interval_seconds"],
            ),
            "hotspot.network_check_interval_seconds",
        )
        reconnect_interval_seconds = _positive_float(
            hotspot.get(
                "reconnect_interval_seconds",
                config["hotspot"]["reconnect_interval_seconds"],
            ),
            "hotspot.reconnect_interval_seconds",
        )
        internet_check_enabled = hotspot.get(
            "internet_check_enabled",
            config["hotspot"]["internet_check_enabled"],
        )
        if not isinstance(internet_check_enabled, bool):
            raise ValueError("'hotspot.internet_check_enabled' must be true or false")
        internet_check_url = hotspot.get(
            "internet_check_url",
            config["hotspot"]["internet_check_url"],
        )
        if not isinstance(internet_check_url, str):
            raise ValueError("'hotspot.internet_check_url' must be a string")
        internet_check_match = hotspot.get(
            "internet_check_match",
            config["hotspot"]["internet_check_match"],
        )
        if not isinstance(internet_check_match, str):
            raise ValueError("'hotspot.internet_check_match' must be a string")
        internet_check_timeout_seconds = _positive_float(
            hotspot.get(
                "internet_check_timeout_seconds",
                config["hotspot"]["internet_check_timeout_seconds"],
            ),
            "hotspot.internet_check_timeout_seconds",
        )
        try:
            failures_before_force = int(
                hotspot.get(
                    "internet_check_failures_before_force",
                    config["hotspot"]["internet_check_failures_before_force"],
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("'hotspot.internet_check_failures_before_force' must be a positive integer") from exc
        if failures_before_force <= 0:
            raise ValueError("'hotspot.internet_check_failures_before_force' must be a positive integer")
        config["hotspot"] = {
            "enabled": enabled,
            "ssid": ssid.strip(),
            "force_on_network_loss": force_on_network_loss,
            "network_check_interval_seconds": network_check_interval_seconds,
            "reconnect_interval_seconds": reconnect_interval_seconds,
            "internet_check_enabled": internet_check_enabled,
            "internet_check_url": internet_check_url.strip(),
            "internet_check_match": internet_check_match,
            "internet_check_timeout_seconds": internet_check_timeout_seconds,
            "internet_check_failures_before_force": failures_before_force,
        }

    return config


def parse_process_names(raw: str) -> list[str]:
    names = [name for name in (_normalize_process_name(part) for part in raw.split(",")) if name]
    if not names:
        raise ValueError("at least one watched process name is required")
    return names


def scan_wifi_networks() -> list[str]:
    """Return saved Wi-Fi networks on macOS."""
    if sys.platform != "darwin":
        return []

    try:
        iface = _wifi_interface()
        result = subprocess.run(
            ["networksetup", "-listpreferredwirelessnetworks", iface],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    networks: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        ssid = line.strip()
        if ssid:
            networks.append(ssid)
    return networks


def run_setup(
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    service_installer: Callable[[bool], Path] | None = None,
) -> dict[str, Any]:
    config = load_config()

    output_func("")
    output_func("=== lid-guard setup ===")
    output_func("")
    output_func("Configure which processes keep your laptop awake on lid close.")
    output_func("")

    current_processes = ", ".join(config["watched_processes"])
    raw_processes = input_func(
        f"Watched process names [{current_processes}]: "
    ).strip()
    if raw_processes:
        config["watched_processes"] = parse_process_names(raw_processes)

    if sys.platform == "darwin":
        output_func("")
        output_func("Would you like to auto-connect to a hotspot on lid close?")
        enabled = _prompt_bool(
            "Enable hotspot auto-connect?",
            config["hotspot"]["enabled"],
            input_func=input_func,
            output_func=output_func,
        )
        config["hotspot"]["enabled"] = enabled
        if enabled:
            config["hotspot"]["ssid"] = _pick_hotspot_ssid(
                current_ssid=config["hotspot"].get("ssid", ""),
                input_func=input_func,
                output_func=output_func,
            )
            output_func("")
            output_func("When protection is active, should lid-guard force the hotspot if Wi-Fi drops?")
            config["hotspot"]["force_on_network_loss"] = _prompt_bool(
                "Force hotspot on network loss?",
                config["hotspot"]["force_on_network_loss"],
                input_func=input_func,
                output_func=output_func,
            )
            if config["hotspot"]["force_on_network_loss"]:
                output_func("")
                output_func("Should lid-guard verify internet access before failing over to the hotspot?")
                config["hotspot"]["internet_check_enabled"] = _prompt_bool(
                    "Use internet reachability checks?",
                    config["hotspot"]["internet_check_enabled"],
                    input_func=input_func,
                    output_func=output_func,
                )
    else:
        output_func("")
        output_func("Hotspot setup is only available on macOS.")

    path = save_config(config)
    output_func("")
    output_func(f"Saved settings to {path}")
    installed_service = False
    if sys.platform in {"linux", "darwin"}:
        output_func("")
        output_func("Would you like lid-guard to keep running automatically in the background?")
        install_background = _prompt_bool(
            "Install background service?",
            False,
            input_func=input_func,
            output_func=output_func,
        )
        if install_background:
            installer = service_installer
            if installer is None:
                from .service import install_service as installer

            try:
                service_path = installer(True)
            except RuntimeError as exc:
                output_func(f"Could not install background service: {exc}")
            else:
                installed_service = True
                output_func(f"Installed background service: {service_path}")

    if not installed_service:
        output_func("Start lid-guard with: lid-guard run")
        if sys.platform in {"linux", "darwin"}:
            output_func("Optional: lid-guard service install")
    output_func("")
    return config


def _normalize_process_name(value: Any) -> str:
    text = str(value).strip().lower()
    return text


def _positive_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be a positive number") from exc
    if result <= 0:
        raise ValueError(f"'{label}' must be a positive number")
    return result


def _wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        lines = result.stdout.splitlines()
        for index, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for offset in range(index + 1, min(index + 4, len(lines))):
                    if lines[offset].startswith("Device:"):
                        return lines[offset].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0"


def _pick_hotspot_ssid(
    current_ssid: str,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> str:
    networks = scan_wifi_networks()
    if networks:
        output_func("")
        output_func("Saved Wi-Fi networks:")
        for index, ssid in enumerate(networks, start=1):
            marker = " (current)" if ssid == current_ssid else ""
            output_func(f"  {index}. {ssid}{marker}")
        output_func("")
        while True:
            raw = input_func("Pick a number or type a network name: ").strip()
            if raw.isdigit():
                choice = int(raw) - 1
                if 0 <= choice < len(networks):
                    return networks[choice]
                output_func(f"Enter a number between 1 and {len(networks)}.")
                continue
            if raw:
                return raw
    else:
        output_func("")
        output_func("No saved networks found.")

    while True:
        manual = input_func("Hotspot SSID: ").strip()
        if manual:
            return manual
        output_func("Enter a non-empty SSID.")


def _prompt_bool(
    prompt: str,
    default: bool,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input_func(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output_func("Please enter y or n.")


load = load_config
save = save_config
