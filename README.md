# lid-guard

Keep your laptop awake when you close the lid so AI coding agents can keep working.

When Claude Code, Codex, or OpenClaw is running, closing your laptop lid locks the screen instead of putting it to sleep. When none of those processes are running, your laptop sleeps normally.

## How it works

1. **Process watcher** — polls every 2 seconds for `claude`, `codex`, or `openclaw` processes.
2. **Sleep inhibitor** — while a watched process is running, prevents system sleep (`caffeinate` on macOS, systemd-logind inhibitor on Linux).
3. **Lid monitor** — detects lid close/open events (`ioreg` on macOS, `/proc/acpi` on Linux).
4. **On lid close** — if protection is active, locks the screen and optionally connects to a Wi-Fi hotspot (macOS). If protection is inactive, the laptop sleeps normally.

## Quickstart

```bash
python3 run.py
```

## Setup (optional)

Configure hotspot auto-connect so your laptop stays online when you close the lid and walk away:

```bash
python3 run.py --setup
```

This lets you pick a saved Wi-Fi network (e.g. your phone's hotspot) to automatically connect to on lid close.

## Install as a service (Linux)

```bash
./install.sh
```

This creates a systemd user service that starts automatically on login.

```bash
# Useful commands after install
systemctl --user status lid-guard
journalctl --user -u lid-guard -f
systemctl --user stop lid-guard
systemctl --user disable --now lid-guard
```

## Platform support

| | macOS | Linux |
|---|---|---|
| Sleep prevention | `caffeinate` | systemd-logind inhibitor (requires `python3-dbus`) |
| Lid detection | `ioreg` (AppleClamshellState) | `/proc/acpi/button/lid` |
| Screen lock | Cmd+Ctrl+Q via AppleScript | `loginctl`, `xdg-screensaver`, `i3lock`, `swaylock`, etc. |
| Hotspot auto-connect | Yes (via `networksetup`) | No |

## Requirements

- Python 3.10+
- **macOS**: No extra dependencies
- **Linux**: `python3-dbus` (`sudo apt install python3-dbus`)

## Config

Settings are stored in `~/.config/lid-guard/config.json`.

## Tip

On macOS, make sure **"Require password immediately"** is enabled in System Settings → Lock Screen so the screen actually locks when the lid closes.
