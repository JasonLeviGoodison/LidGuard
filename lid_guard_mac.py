#!/usr/bin/env python3
"""
lid-guard (macOS): Keep your laptop awake on lid close, lock the screen instead.

Activates ONLY when Claude Code or openclaw is running.

How it works:
  - Watches for 'claude' or 'openclaw' processes (process_watcher.py).
  - While a watched process is running:
      * Runs caffeinate to prevent system/display sleep.
      * On lid close → locks the screen instead of sleeping.
  - When no watched process is running:
      * Stops caffeinate — lid close / idle sleep behave normally.

Run directly:
  python3 lid_guard_mac.py
"""

import sys
import time
import signal
import subprocess
import logging
import threading

from process_watcher import ProcessWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lid-guard-mac")


# ---------------------------------------------------------------------------
# Screen locking (macOS)
# ---------------------------------------------------------------------------

def lock_screen() -> bool:
    # Cmd+Ctrl+Q: built-in macOS lock shortcut (10.13+), most reliable
    script = 'tell application "System Events" to keystroke "q" using {command down, control down}'
    try:
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
        log.info("Screen locked via AppleScript (Cmd+Ctrl+Q)")
        return True
    except Exception as e:
        log.debug("AppleScript lock failed: %s", e)

    # Fallback: start the screensaver (locks if "require password immediately" is on)
    try:
        result = subprocess.run(
            ["open", "-a", "ScreenSaverEngine"], timeout=5, capture_output=True
        )
        if result.returncode == 0:
            log.info("Screen locked via ScreenSaverEngine")
            return True
    except Exception:
        pass

    # Last resort: display sleep
    try:
        subprocess.run(["pmset", "displaysleepnow"], timeout=5, capture_output=True)
        log.info("Display sleep triggered via pmset")
        return True
    except Exception:
        pass

    log.error("Could not lock screen on macOS")
    return False


# ---------------------------------------------------------------------------
# caffeinate guard (prevents sleep)
# ---------------------------------------------------------------------------

class CaffeinateGuard:
    """Runs caffeinate to hold off system/display sleep. Start/stop dynamically."""

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self):
        with self._lock:
            if self.active:
                return
            try:
                self._proc = subprocess.Popen(
                    ["caffeinate", "-d", "-i"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info("caffeinate started (pid=%d) — sleep inhibited", self._proc.pid)
            except FileNotFoundError:
                log.error("caffeinate not found — should be built into macOS")

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc.wait(timeout=3)
                log.info("caffeinate stopped — normal sleep restored")
            self._proc = None


# ---------------------------------------------------------------------------
# Lid state monitoring (macOS)
# ---------------------------------------------------------------------------

def _get_lid_state() -> bool | None:
    """True = closed, False = open, None = unknown. Uses ioreg."""
    try:
        result = subprocess.run(
            ["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.splitlines():
            if "AppleClamshellState" in line:
                return "Yes" in line or "true" in line.lower()
    except Exception as e:
        log.debug("ioreg lid check failed: %s", e)
    return None


class LidMonitor:
    POLL_INTERVAL = 0.3

    def __init__(self, on_close, on_open=None):
        self._on_close = on_close
        self._on_open = on_open
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="lid-monitor")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _poll_loop(self):
        log.info("Lid monitor started (polling ioreg every %.1fs)", self.POLL_INTERVAL)
        last_state = _get_lid_state()

        while self._running:
            time.sleep(self.POLL_INTERVAL)
            current = _get_lid_state()
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
        self._caffeinate = CaffeinateGuard()
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
        self._caffeinate.start()

    def _on_processes_idle(self):
        self._caffeinate.stop()

    # -- Lid event callbacks ------------------------------------------------

    def _handle_lid_close(self):
        if self._caffeinate.active:
            log.info("Lid CLOSED and protection is ACTIVE — locking screen")
            lock_screen()
        else:
            log.info("Lid CLOSED but no watched process running — letting Mac sleep")

    def _handle_lid_open(self):
        log.info("Lid OPENED")

    # -- Lifecycle ----------------------------------------------------------

    def _handle_signal(self, sig, _frame):
        log.info("Received signal %d — shutting down gracefully", sig)
        self._stop_event.set()

    def run(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        state = _get_lid_state()
        if state is None:
            log.warning("Cannot read lid state via ioreg — lid monitoring may not work.")
        else:
            log.info("Lid is currently: %s", "CLOSED" if state else "OPEN")

        self._watcher.start()
        self._monitor.start()

        log.info(
            "lid-guard is running.\n"
            "  Watching for: claude, openclaw\n"
            "  Active  → lid close locks screen, Mac stays awake\n"
            "  Inactive → lid close sleeps normally\n"
            "  Ctrl-C / SIGTERM to exit\n"
            "\n"
            "  Tip: ensure 'Require password immediately' is ON in\n"
            "  System Settings → Lock Screen"
        )

        self._stop_event.wait()
        self._monitor.stop()
        self._watcher.stop()
        self._caffeinate.stop()
        log.info("lid-guard stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if sys.platform != "darwin":
        print("This script is for macOS. On Linux use: python3 lid_guard.py")
        sys.exit(1)

    log.info("Starting lid-guard (macOS)")
    LidGuard().run()


if __name__ == "__main__":
    main()
