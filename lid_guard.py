#!/usr/bin/env python3
"""
lid-guard (Linux): Keep your laptop awake when you close the lid, but lock the screen.

Activates ONLY when Claude Code or openclaw is running.

How it works:
  - Watches for 'claude' or 'openclaw' processes (process_watcher.py).
  - While a watched process is running:
      * Holds a systemd-logind 'handle-lid-switch' inhibitor — prevents
        logind from sleeping when the lid closes.
      * On lid close → locks the screen instead of sleeping.
  - When no watched process is running:
      * Releases the inhibitor — lid close behaves normally (OS sleep).

Run directly:
  python3 lid_guard.py

Install as a systemd user service:
  ./install.sh
"""

import os
import sys
import time
import signal
import subprocess
import logging
import threading
from pathlib import Path

from process_watcher import ProcessWatcher

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lid-guard")


# ---------------------------------------------------------------------------
# Screen locking
# ---------------------------------------------------------------------------

_LOCK_COMMANDS = [
    ["loginctl", "lock-session"],
    ["xdg-screensaver", "lock"],
    ["gnome-screensaver-command", "--lock"],
    ["dbus-send", "--session", "--dest=org.gnome.ScreenSaver",
     "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.Lock"],
    ["qdbus", "org.kde.screensaver", "/ScreenSaver", "Lock"],
    ["swaylock", "--daemonize"],
    ["xlock"],
    ["i3lock"],
]


def lock_screen() -> bool:
    for cmd in _LOCK_COMMANDS:
        try:
            result = subprocess.run(cmd, timeout=5, capture_output=True)
            if result.returncode == 0:
                log.info("Screen locked via: %s", cmd[0])
                return True
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            log.warning("Lock command timed out: %s", cmd[0])
        except Exception as e:
            log.debug("Lock command %s failed: %s", cmd[0], e)
    log.error(
        "Could not lock screen — no supported locker found.\n"
        "Install one of: loginctl (systemd), xdg-screensaver, i3lock, swaylock"
    )
    return False


# ---------------------------------------------------------------------------
# Inhibitor lock
# ---------------------------------------------------------------------------

class InhibitorLock:
    """
    Holds a systemd-logind 'handle-lid-switch' block inhibitor.
    Acquire to prevent sleep on lid close; release to restore normal behaviour.
    """

    def __init__(self):
        self._fd: int | None = None
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        with self._lock:
            if self._fd is not None:
                return True  # already held
            try:
                import dbus
                bus = dbus.SystemBus()
                mgr = dbus.Interface(
                    bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1"),
                    "org.freedesktop.login1.Manager",
                )
                fd_obj = mgr.Inhibit(
                    "handle-lid-switch",
                    "lid-guard",
                    "Lock screen instead of sleeping on lid close",
                    "block",
                )
                self._fd = fd_obj.take()
                log.info("Inhibitor lock acquired (fd=%d)", self._fd)
                return True
            except ImportError:
                log.warning(
                    "python3-dbus not found — install with: sudo apt install python3-dbus\n"
                    "  Without it the inhibitor won't work and logind may still sleep."
                )
                return False
            except Exception as e:
                log.error("D-Bus inhibitor failed: %s", e)
                return False

    def release(self):
        with self._lock:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                    log.info("Inhibitor lock released — lid will sleep normally")
                except OSError:
                    pass
                self._fd = None


# ---------------------------------------------------------------------------
# Lid state monitoring
# ---------------------------------------------------------------------------

def _read_lid_state() -> bool | None:
    """True = closed, False = open, None = unknown."""
    for state_file in Path("/proc/acpi/button/lid").glob("*/state"):
        try:
            return "closed" in state_file.read_text()
        except OSError:
            pass
    return None


class LidMonitor:
    POLL_INTERVAL = 0.3

    def __init__(self, on_close, on_open=None):
        self._on_close = on_close
        self._on_open = on_open
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="lid-monitor")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _poll_loop(self):
        log.info("Lid monitor started (polling /proc/acpi every %.1fs)", self.POLL_INTERVAL)
        last_state = _read_lid_state()

        while self._running:
            time.sleep(self.POLL_INTERVAL)
            current = _read_lid_state()
            if current is None:
                continue
            if last_state is False and current is True:
                self._on_close()
            elif last_state is True and current is False:
                if self._on_open:
                    self._on_open()
            last_state = current


# ---------------------------------------------------------------------------
# Main daemon
# ---------------------------------------------------------------------------

class LidGuard:

    def __init__(self):
        self._inhibitor = InhibitorLock()
        self._monitor = LidMonitor(
            on_close=self._handle_lid_close,
            on_open=self._handle_lid_open,
        )
        self._watcher = ProcessWatcher(
            on_active=self._on_processes_active,
            on_idle=self._on_processes_idle,
        )
        self._stop_event = threading.Event()

    # -- Process watcher callbacks ------------------------------------------

    def _on_processes_active(self):
        """A watched process just appeared — grab the inhibitor."""
        self._inhibitor.acquire()

    def _on_processes_idle(self):
        """All watched processes gone — release inhibitor (normal sleep resumes)."""
        self._inhibitor.release()

    # -- Lid event callbacks ------------------------------------------------

    def _handle_lid_close(self):
        if self._inhibitor.held:
            log.info("Lid CLOSED and protection is ACTIVE — locking screen")
            lock_screen()
        else:
            log.info("Lid CLOSED but no watched process running — letting OS sleep")

    def _handle_lid_open(self):
        log.info("Lid OPENED")

    # -- Lifecycle ----------------------------------------------------------

    def _handle_signal(self, sig, _frame):
        log.info("Received signal %d — shutting down gracefully", sig)
        self._stop_event.set()

    def run(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        if _read_lid_state() is None:
            log.warning(
                "/proc/acpi/button/lid not found — lid detection may not work.\n"
                "  Check: ls /proc/acpi/button/lid/"
            )

        self._watcher.start()
        self._monitor.start()

        log.info(
            "lid-guard is running.\n"
            "  Watching for: claude, openclaw\n"
            "  Active  → lid close locks screen, laptop stays awake\n"
            "  Inactive → lid close sleeps normally\n"
            "  Ctrl-C / SIGTERM to exit\n"
        )

        self._stop_event.wait()
        self._monitor.stop()
        self._watcher.stop()
        self._inhibitor.release()
        log.info("lid-guard stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if sys.platform != "linux":
        log.error("lid-guard only works on Linux (uses systemd-logind + /proc/acpi)")
        sys.exit(1)

    log.info("Starting lid-guard")
    LidGuard().run()


if __name__ == "__main__":
    main()
