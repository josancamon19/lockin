"""Watchdog daemon loop and launchd plist management."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from lockin import blocker, apps, session

PLIST_LABEL = "com.lockin.watchdog"
PLIST_PATH = Path(f"/Library/LaunchDaemons/{PLIST_LABEL}.plist")
LOG_FILE = Path("/var/log/lockin.log")
ERROR_LOG_FILE = Path("/var/log/lockin_error.log")
WATCHDOG_INTERVAL = 3  # seconds


def _log(msg: str) -> None:
    """Append a log message to the daemon log file."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except OSError:
        pass


def generate_plist() -> dict:
    """Generate the launchd plist dict for the watchdog daemon."""
    python_path = sys.executable
    return {
        "Label": PLIST_LABEL,
        "ProgramArguments": [python_path, "-m", "lockin.daemon"],
        "KeepAlive": True,
        "RunAtLoad": True,
        "StandardOutPath": str(LOG_FILE),
        "StandardErrorPath": str(ERROR_LOG_FILE),
    }


def install_daemon() -> bool:
    """Install the launchd watchdog daemon.

    Returns True if installed successfully.
    """
    if os.geteuid() != 0:
        return False

    plist_data = generate_plist()

    # Unload existing if present
    if PLIST_PATH.exists():
        # Remove immutable flag if set
        subprocess.run(["chflags", "noschg", str(PLIST_PATH)], capture_output=True)
        subprocess.run(
            ["launchctl", "bootout", f"system/{PLIST_LABEL}"],
            capture_output=True,
        )

    # Write plist
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)

    # Set ownership and permissions
    os.chmod(PLIST_PATH, 0o644)
    os.chown(PLIST_PATH, 0, 0)  # root:wheel

    # Protect with immutable flag
    subprocess.run(["chflags", "schg", str(PLIST_PATH)], capture_output=True)

    # Load the daemon
    result = subprocess.run(
        ["launchctl", "bootstrap", "system", str(PLIST_PATH)],
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


def uninstall_daemon() -> bool:
    """Uninstall the launchd watchdog daemon."""
    if os.geteuid() != 0:
        return False

    # Remove immutable flag
    subprocess.run(["chflags", "noschg", str(PLIST_PATH)], capture_output=True)

    # Unload
    subprocess.run(
        ["launchctl", "bootout", f"system/{PLIST_LABEL}"],
        capture_output=True,
    )

    # Remove plist file
    try:
        PLIST_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    return True


def is_daemon_installed() -> bool:
    """Check if the daemon plist exists."""
    return PLIST_PATH.exists()


def _enforce_blocks(sess: session.Session) -> None:
    """Re-apply all blocks for the active session."""
    # Ensure hosts blocks are present
    if not blocker.are_blocks_applied(sess.blocked_domains):
        _log("Blocks missing from /etc/hosts, re-applying")
        blocker.apply_blocks(sess.blocked_domains)

    # Ensure immutable flag is set
    if not blocker.is_immutable():
        _log("Immutable flag missing, re-setting")
        blocker.set_immutable_flag()

    # Kill blocked apps
    killed = apps.kill_blocked_apps(sess.blocked_apps)
    if killed:
        _log(f"Killed blocked apps: {', '.join(killed)}")


def _cleanup(sess: session.Session) -> None:
    """Remove all blocks and clean up after a valid expired session."""
    _log("Session expired, cleaning up blocks")
    blocker.remove_blocks()
    session.delete_session()
    _log("Cleanup complete")


def watchdog_loop() -> None:
    """Main watchdog loop — runs every WATCHDOG_INTERVAL seconds."""
    _log("Watchdog daemon started")

    while True:
        try:
            sess = session.load_session()

            if sess is None:
                # No session file — could be deleted (blocks stay permanent)
                # or simply no session active. Check if hosts has our blocks.
                try:
                    content = blocker.HOSTS_FILE.read_text()
                    if blocker.BLOCK_START in content:
                        _log("WARNING: No session file but blocks exist — keeping blocks permanent")
                except OSError:
                    pass
                time.sleep(WATCHDOG_INTERVAL)
                continue

            if not sess.verify():
                # Tampered session — keep blocks, refuse to clean up
                _log("WARNING: Session file HMAC invalid — tampered! Keeping blocks.")
                time.sleep(WATCHDOG_INTERVAL)
                continue

            if sess.is_clock_tampered():
                _log("WARNING: Clock tampering detected — refusing to clean up")
                time.sleep(WATCHDOG_INTERVAL)
                continue

            if sess.is_expired:
                # Valid expired session — clean up
                _cleanup(sess)
                time.sleep(WATCHDOG_INTERVAL)
                continue

            # Active valid session — enforce blocks
            _enforce_blocks(sess)

        except Exception as e:
            _log(f"ERROR in watchdog loop: {e}")

        time.sleep(WATCHDOG_INTERVAL)


if __name__ == "__main__":
    watchdog_loop()
