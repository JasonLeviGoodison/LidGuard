# lid-guard

`lid-guard` is an open source CLI that keeps your laptop awake when you close the lid, but only while selected coding-agent processes are running.

If nothing important is running, lid close goes back to normal OS behavior. If protection is active, `lid-guard` keeps the machine awake and locks the screen instead.

## Why It Exists

Laptop lid behavior is usually binary:

- close the lid and sleep immediately
- keep the laptop open if you want long-running work to continue

That breaks down when you want agents like `codex`, `claude`, or `openclaw` to keep running while you step away. `lid-guard` turns that into a policy:

- protected when watched processes are active
- normal again when they are not

## What It Does

On macOS:

- starts `caffeinate` while watched processes are active
- locks the screen on lid close
- can reconnect to a configured hotspot
- can keep checking connectivity and force the hotspot if Wi‑Fi drops or internet checks fail

On Linux:

- acquires a `systemd-logind` lid-switch inhibitor while watched processes are active
- locks the screen on lid close
- releases the inhibitor when watched processes stop

## Install

### Curl

```bash
curl -fsSL https://raw.githubusercontent.com/JasonLeviGoodison/AlwaysGrinding/main/scripts/install-from-github.sh | bash
```

Install a tagged release instead of `main`:

```bash
curl -fsSL https://raw.githubusercontent.com/JasonLeviGoodison/AlwaysGrinding/main/scripts/install-from-github.sh | env LID_GUARD_VERSION=vX.Y.Z bash
```

### Homebrew

```bash
brew install --HEAD https://raw.githubusercontent.com/JasonLeviGoodison/AlwaysGrinding/main/Formula/lid-guard.rb
```

This builds the standalone CLI from the repository formula.

### Local Installer

```bash
./install.sh
```

That builds a standalone `.pyz` archive under `~/.local/share/lid-guard` and links `lid-guard` into `~/.local/bin`.

### Run From Source

```bash
python3 run.py run
```

## Quick Start

```bash
lid-guard doctor
lid-guard setup
lid-guard run
```

`lid-guard setup` can also offer to install the background service for you.

Install a background service directly:

```bash
lid-guard service install
```

## Commands

```bash
lid-guard run
lid-guard setup
lid-guard doctor
lid-guard service install
lid-guard service uninstall
```

Override watched processes for a single run:

```bash
lid-guard run --watch-process codex --watch-process aider
```

## Configuration

Configuration is stored in:

- Linux: `~/.config/lid-guard/config.json`
- macOS: `~/Library/Application Support/lid-guard/config.json`

Config includes:

- watched process names
- process polling interval
- lid polling interval
- hotspot SSID on macOS
- hotspot failover behavior on macOS

Run the setup wizard to populate it:

```bash
lid-guard setup
```

## macOS Hotspot Notes

`lid-guard` can tell macOS to join a configured hotspot, but Apple still controls Instant Hotspot availability.

For the best results:

- use an iPhone or iPad with Personal Hotspot enabled on your carrier plan
- keep Wi‑Fi and Bluetooth on for both devices
- sign both devices into the same Apple Account, or use Family Sharing
- set macOS Auto-Join Hotspot to `Automatic` if available

Apple’s current support docs say Auto-Join Hotspot `Automatic` is available on macOS Tahoe 26 or later, and that `Allow Others to Join` does not need to be enabled for same-account Instant Hotspot:

- https://support.apple.com/en-my/109321

## Platform Notes

### macOS

- Uses `caffeinate`, `ioreg`, `osascript`, and `networksetup`
- Screen locking depends on standard macOS lock mechanisms
- For strong lock behavior, require a password immediately after screen lock in System Settings

### Linux

- Uses `/proc/acpi/button/lid/*/state` for lid polling
- Uses `python3-dbus` for the logind inhibitor
- Works best on systemd-based desktops with an available screen locker

If `python3-dbus` is missing, lid inhibition will not work reliably.

## Releases

Tagging `v*` releases builds and publishes the standalone `lid-guard.pyz` archive through GitHub Actions.

You can also build it manually:

```bash
python3 scripts/build_zipapp.py
./dist/lid-guard.pyz --version
```

## Development

Install for development:

```bash
python3 -m pip install wheel
python3 -m pip install --no-build-isolation .
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```
