"""
config.py — load/save lid-guard settings and manage Keychain secrets (macOS).

Config file: ~/.config/lid-guard/config.json
Keychain:    service="lid-guard", account="hotspot-password"
"""

import json
import subprocess
import sys
import time
import logging
import getpass
from pathlib import Path

log = logging.getLogger("lid-guard.config")

CONFIG_DIR  = Path.home() / ".config" / "lid-guard"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "hotspot": {
        "enabled": False,
        "ssid": "",
    }
}

# airport binary (removed in macOS Sonoma but still present on older versions)
_AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------

def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            merged = json.loads(json.dumps(DEFAULTS))
            _deep_merge(merged, data)
            return merged
        except Exception as e:
            log.warning("Could not read config (%s) — using defaults", e)
    return json.loads(json.dumps(DEFAULTS))


def save(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    log.debug("Config saved to %s", CONFIG_FILE)


def _deep_merge(base: dict, override: dict):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Wi-Fi network scanning (macOS)
# ---------------------------------------------------------------------------

def scan_wifi_networks() -> list[str]:
    """
    Return a list of nearby Wi-Fi SSIDs, sorted by signal strength.

    Tries `airport -s` first (macOS < Sonoma), then falls back to
    `networksetup -listpreferredwirelessnetworks` (saved networks).
    """
    ssids = _scan_via_airport()
    if ssids:
        return ssids
    return _scan_via_networksetup()


def _scan_via_airport() -> list[str]:
    """Use the airport binary to scan for live nearby networks."""
    try:
        result = subprocess.run(
            [_AIRPORT, "-s"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []

        ssids = []
        seen = set()
        # airport output: header line then one network per line
        # columns: SSID  BSSID  RSSI  CHANNEL  HT  CC  SECURITY
        # SSID is right-aligned in a fixed-width field — everything before the BSSID (MAC addr)
        for line in result.stdout.splitlines()[1:]:  # skip header
            # MAC address pattern marks where SSID ends
            parts = line.rsplit(None, 6)  # split from right
            if len(parts) >= 7:
                ssid = parts[0].strip()
                if ssid and ssid not in seen:
                    seen.add(ssid)
                    ssids.append(ssid)
        return ssids
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []


def _scan_via_networksetup() -> list[str]:
    """Fallback: list networks already saved in macOS preferred network list."""
    try:
        iface = _wifi_interface()
        result = subprocess.run(
            ["networksetup", "-listpreferredwirelessnetworks", iface],
            capture_output=True, text=True, timeout=5,
        )
        ssids = []
        for line in result.stdout.splitlines()[1:]:  # skip header
            ssid = line.strip()
            if ssid:
                ssids.append(ssid)
        return ssids
    except Exception:
        return []


def _wifi_interface() -> str:
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0"


# ---------------------------------------------------------------------------
# Keychain (macOS only)
# ---------------------------------------------------------------------------

_KEYCHAIN_SERVICE = "lid-guard"
_KEYCHAIN_ACCOUNT = "hotspot-password"


def keychain_save_password(password: str) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(
            ["security", "delete-generic-password",
             "-s", _KEYCHAIN_SERVICE, "-a", _KEYCHAIN_ACCOUNT],
            capture_output=True,
        )
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", _KEYCHAIN_SERVICE,
             "-a", _KEYCHAIN_ACCOUNT,
             "-w", password],
            capture_output=True,
        )
        return result.returncode == 0
    except Exception as e:
        log.error("Keychain save failed: %s", e)
        return False


def keychain_load_password() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", _KEYCHAIN_SERVICE,
             "-a", _KEYCHAIN_ACCOUNT,
             "-w"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        log.error("Keychain load failed: %s", e)
    return None


def keychain_delete_password():
    if sys.platform != "darwin":
        return
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", _KEYCHAIN_SERVICE, "-a", _KEYCHAIN_ACCOUNT],
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Setup wizard
# ---------------------------------------------------------------------------

def run_setup():
    print("\n=== lid-guard setup ===\n")
    print("lid-guard keeps your laptop awake when you close the lid so that")
    print("Claude Code, Codex, or openclaw can keep running.\n")

    cfg = load()

    # ── Hotspot question ────────────────────────────────────────────────────
    print("Would you like to auto-connect to a hotspot when you close the lid?")
    print("This keeps your processes online when you unplug and walk away.\n")

    enabled = _prompt_bool("Enable hotspot auto-connect?", cfg["hotspot"]["enabled"])
    cfg["hotspot"]["enabled"] = enabled

    if enabled:
        ssid = _pick_hotspot_ssid(cfg["hotspot"].get("ssid", ""))
        cfg["hotspot"]["ssid"] = ssid
        _configure_password(ssid)
        print(f"\n  Hotspot set to: {ssid!r}")
    else:
        print("\n  Hotspot auto-connect: off")

    # ── Save ────────────────────────────────────────────────────────────────
    save(cfg)
    print(f"\nSettings saved to {CONFIG_FILE}")
    print("Start lid-guard with:  python3 run.py\n")


def _pick_hotspot_ssid(current_ssid: str) -> str:
    """
    Guide the user to turn on their hotspot, scan for networks,
    and pick one from a numbered list.
    """
    print("\nTurn on your phone's Personal Hotspot now, then press Enter to scan.")
    print("(Settings → Personal Hotspot → Allow Others to Join)\n")
    input("  Press Enter when your hotspot is on… ")

    print("\n  Scanning for networks", end="", flush=True)
    for _ in range(3):
        time.sleep(0.6)
        print(".", end="", flush=True)

    networks = scan_wifi_networks()
    print()  # newline after dots

    if networks:
        print(f"\n  Found {len(networks)} network(s):\n")
        for i, ssid in enumerate(networks, 1):
            marker = "  (current)" if ssid == current_ssid else ""
            print(f"    {i:2}.  {ssid}{marker}")
        print()

        while True:
            raw = input("  Pick a number, or type a name manually: ").strip()
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(networks):
                    return networks[idx]
                print(f"  Please enter a number between 1 and {len(networks)}.")
            elif raw:
                return raw
    else:
        print("\n  No networks found — hotspot may not be visible yet.")
        print("  You can type the name manually:\n")
        while True:
            name = input("  Hotspot name: ").strip()
            if name:
                return name


def _configure_password(ssid: str):
    """Ask for the hotspot password and save it to Keychain."""
    existing = keychain_load_password()

    if existing:
        print(f"\n  A password is already saved in Keychain for this setup.")
        change = _prompt_bool("  Update the password?", False)
        if not change:
            return

    print(f"\n  Enter the password for {ssid!r}.")
    print("  (It will be stored in macOS Keychain — not in any file.)\n")

    while True:
        password = getpass.getpass("  Password (Enter to skip): ").strip()
        if not password:
            if not existing:
                print("  No password saved — will only connect if SSID is already in Known Networks.")
            return
        confirm = getpass.getpass("  Confirm password: ").strip()
        if password == confirm:
            break
        print("  Passwords don't match, try again.\n")

    if keychain_save_password(password):
        print("  Password saved to Keychain.")
    else:
        print("  Warning: could not save to Keychain.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt_bool(prompt: str, default: bool) -> bool:
    default_str = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{default_str}]: ").strip().lower()
        if answer == "":
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please enter y or n.")
