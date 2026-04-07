"""
process_watcher.py — watches for specific processes and fires callbacks.

Used by lid-guard to decide whether to hold the sleep inhibitor:
  - Any watched process starts  → on_active()
  - All watched processes stop  → on_idle()
"""

import subprocess
import threading
import logging
import time

log = logging.getLogger("lid-guard.procs")

# Processes that activate lid-guard protection.
# Matched against the full command line (pgrep -f), so partial names work.
WATCHED_PROCESSES = [
    "claude",       # Claude Code CLI
    "openclaw",     # OpenClaw
    "codex",        # OpenAI Codex CLI
]


def any_watched_running(processes: list[str] = WATCHED_PROCESSES) -> bool:
    """Return True if any of the watched process names are currently running."""
    for name in processes:
        try:
            result = subprocess.run(
                ["pgrep", "-f", name],
                capture_output=True,
            )
            if result.returncode == 0:
                log.debug("Found watched process: %s", name)
                return True
        except FileNotFoundError:
            # pgrep not available — fall back to /proc scan (Linux only)
            if _proc_scan(name):
                return True
    return False


def _proc_scan(name: str) -> bool:
    """Scan /proc/*/cmdline for the process name (Linux fallback if pgrep missing)."""
    import os
    from pathlib import Path
    try:
        for cmdline_file in Path("/proc").glob("*/cmdline"):
            try:
                content = cmdline_file.read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
                if name in content:
                    return True
            except OSError:
                pass
    except Exception:
        pass
    return False


class ProcessWatcher:
    """
    Polls for watched processes on a background thread.

    Fires on_active() when at least one watched process appears.
    Fires on_idle()   when all watched processes have stopped.
    """

    POLL_INTERVAL = 2.0  # seconds between checks

    def __init__(self, on_active, on_idle, processes: list[str] = WATCHED_PROCESSES):
        self._on_active = on_active
        self._on_idle = on_idle
        self._processes = processes
        self._running = False
        self._thread: threading.Thread | None = None
        self._active: bool | None = None  # None = unknown (first poll)

    @property
    def is_active(self) -> bool:
        """True if a watched process was detected on the last poll."""
        return bool(self._active)

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="proc-watcher"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.POLL_INTERVAL + 1)

    def _poll_loop(self):
        log.info(
            "Process watcher started — watching: %s (every %.0fs)",
            ", ".join(self._processes),
            self.POLL_INTERVAL,
        )
        while self._running:
            current = any_watched_running(self._processes)

            if self._active is None:
                # First poll — record state and fire callback if already active
                self._active = current
                if current:
                    log.info("Watched process already running — protection is ACTIVE")
                    self._on_active()
                else:
                    log.info("No watched process running — protection is INACTIVE")

            elif current and not self._active:
                self._active = True
                log.info("Watched process detected — protection ACTIVATED")
                self._on_active()

            elif not current and self._active:
                self._active = False
                log.info("No watched processes — protection DEACTIVATED")
                self._on_idle()

            time.sleep(self.POLL_INTERVAL)
