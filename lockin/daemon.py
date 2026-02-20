"""Watchdog daemon loop and launchd plist management."""

from __future__ import annotations

import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lockin import blocker, apps, session

PLIST_LABEL = "com.lockin.watchdog"
PLIST_PATH = Path(f"/Library/LaunchDaemons/{PLIST_LABEL}.plist")
LOG_FILE = Path("/var/log/lockin.log")
ERROR_LOG_FILE = Path("/var/log/lockin_error.log")
WATCHDOG_INTERVAL = 3  # seconds
SCHEDULE_STATE_FILE = Path("/var/lockin/schedule_state.json")


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


def _get_package_paths() -> list[Path]:
    """Derive paths to protect from pipx uninstall during active sessions.

    Protects the venv entry points, the package site-packages dir,
    and the pipx bin symlinks.
    """
    paths: list[Path] = []
    venv_root = Path(sys.prefix)  # e.g. ~/.local/pipx/venvs/lockin

    # Venv bin dir (contains the lockin entry point script)
    venv_bin = venv_root / "bin"
    if venv_bin.exists():
        paths.append(venv_bin)

    # Site-packages lockin dir
    vi = sys.version_info
    site_pkg = venv_root / "lib" / f"python{vi.major}.{vi.minor}" / "site-packages" / "lockin"
    if site_pkg.exists():
        paths.append(site_pkg)

    # pipx bin symlinks (e.g. ~/.local/bin/lockin)
    pipx_bin = Path.home() / ".local" / "bin"
    if pipx_bin.exists():
        for name in ("lockin", "lockin-menubar"):
            p = pipx_bin / name
            if p.exists():
                paths.append(p)

    return paths


def _protect_package(protect: bool = True) -> None:
    """Set or remove schg on package paths to prevent pipx uninstall."""
    flag = "schg" if protect else "noschg"
    for p in _get_package_paths():
        subprocess.run(["chflags", flag, str(p)], capture_output=True)


def _protect_plist() -> None:
    """Verify the daemon plist exists, is immutable, and is registered with launchd.

    Re-creates and re-bootstraps if anything is missing.
    """
    needs_bootstrap = False

    if not PLIST_PATH.exists():
        _log("Plist missing, re-creating")
        plist_data = generate_plist()
        with open(PLIST_PATH, "wb") as f:
            plistlib.dump(plist_data, f)
        os.chmod(PLIST_PATH, 0o644)
        os.chown(PLIST_PATH, 0, 0)
        needs_bootstrap = True

    # Ensure immutable flag
    result = subprocess.run(
        ["ls", "-lO", str(PLIST_PATH)], capture_output=True, text=True
    )
    if "schg" not in result.stdout:
        subprocess.run(["chflags", "schg", str(PLIST_PATH)], capture_output=True)

    # Check launchd registration
    result = subprocess.run(
        ["launchctl", "print", f"system/{PLIST_LABEL}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        needs_bootstrap = True

    if needs_bootstrap:
        _log("Re-bootstrapping daemon plist")
        subprocess.run(
            ["launchctl", "bootstrap", "system", str(PLIST_PATH)],
            capture_output=True,
        )


def _enforce_blocks(sess: session.Session) -> None:
    """Re-apply all protection layers for the active session."""
    # 1. Hosts blocks
    if not blocker.are_blocks_applied(sess.blocked_domains):
        _log("Blocks missing from /etc/hosts, re-applying")
        blocker.apply_blocks(sess.blocked_domains)

    # 2. Hosts immutable flag
    if not blocker.is_immutable():
        _log("Immutable flag missing, re-setting")
        blocker.set_immutable_flag()

    # 3. pfctl rules
    if not blocker.are_pfctl_rules_applied():
        _log("pfctl rules missing, re-applying")
        blocker.apply_pfctl_rules(sess.blocked_domains)

    # 4. Session file immutable
    if not session.is_session_immutable():
        _log("Session file immutable flag missing, re-setting")
        session.set_session_immutable()

    # 5. Plist protected
    _protect_plist()

    # 6. Package protected
    _protect_package(protect=True)

    # 7. Kill blocked apps
    killed = apps.kill_blocked_apps(sess.blocked_apps)
    if killed:
        _log(f"Killed blocked apps: {', '.join(killed)}")


def _cleanup(sess: session.Session) -> None:
    """Remove all protections and clean up after a valid expired session."""
    _log("Session expired, cleaning up")

    # 1. Remove package protection
    _protect_package(protect=False)

    # 2. Remove session immutability + delete session
    session.delete_session()

    # 3. Remove hosts blocks + pfctl rules
    blocker.remove_blocks()

    _log("Cleanup complete")


def _load_schedule_state() -> dict[str, str]:
    """Load schedule trigger state: {schedule_name: "YYYY-MM-DD"}."""
    try:
        if SCHEDULE_STATE_FILE.exists():
            return json.loads(SCHEDULE_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_schedule_state(state: dict[str, str]) -> None:
    """Write schedule trigger state to disk."""
    try:
        SCHEDULE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEDULE_STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    except OSError:
        pass


def _get_local_timezone() -> str | None:
    """Detect the system IANA timezone name from /etc/localtime symlink."""
    try:
        link = Path("/etc/localtime").resolve()
        # e.g. /usr/share/zoneinfo/America/New_York -> America/New_York
        parts = link.parts
        idx = parts.index("zoneinfo")
        return "/".join(parts[idx + 1 :])
    except (ValueError, OSError):
        return None


def _check_schedules() -> None:
    """Check all schedules and trigger any that match the current time window."""
    from lockin.config import load_config, resolve_blocked_lists

    config = load_config()
    if not config.schedules:
        return

    state = _load_schedule_state()

    # Prune stale entries for deleted schedules
    stale_keys = [k for k in state if k not in config.schedules]
    for k in stale_keys:
        del state[k]
    if stale_keys:
        _save_schedule_state(state)

    for name, schedule in config.schedules.items():
        try:
            _try_trigger_schedule(name, schedule, config, state)
        except Exception as e:
            _log(f"ERROR checking schedule '{name}': {e}")


def _try_trigger_schedule(
    name: str,
    schedule: object,
    config: object,
    state: dict[str, str],
) -> None:
    """Evaluate whether a single schedule should fire now."""
    from lockin.config import resolve_blocked_lists

    # Resolve timezone
    tz_name = schedule.timezone or _get_local_timezone()
    if not tz_name:
        _log(f"Schedule '{name}': cannot determine timezone, skipping")
        return

    try:
        tz = ZoneInfo(tz_name)
    except (KeyError, Exception):
        _log(f"Schedule '{name}': invalid timezone '{tz_name}', skipping")
        return

    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    today_day_name = now.strftime("%A")  # e.g. "Monday"

    # Check day matches
    if today_day_name not in schedule.days:
        return

    # Check not already triggered today
    if state.get(name) == today_str:
        return

    # Parse start time
    try:
        hour, minute = map(int, schedule.start_time.split(":"))
    except (ValueError, AttributeError):
        _log(f"Schedule '{name}': invalid start_time '{schedule.start_time}', skipping")
        return

    window_start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=schedule.duration_minutes)

    # Check current time is within the window
    if not (window_start <= now < window_end):
        return

    # Calculate remaining seconds
    remaining_seconds = int((window_end - now).total_seconds())
    if remaining_seconds < 60:
        _log(f"Schedule '{name}': less than 60s remaining in window, skipping")
        return

    # Check if there's already an active session
    active = session.load_session()
    if active and active.verify() and not active.is_expired:
        return

    # Resolve profile
    profile = config.profiles.get(schedule.profile)
    if profile is None:
        _log(f"Schedule '{name}': profile '{schedule.profile}' not found, skipping")
        return

    blocked_domains, blocked_apps = resolve_blocked_lists(profile, config.always_blocked)
    if not blocked_domains and not blocked_apps:
        _log(f"Schedule '{name}': profile '{schedule.profile}' has nothing to block, skipping")
        return

    # Apply blocks
    _log(f"Schedule '{name}' triggered: profile={schedule.profile}, remaining={remaining_seconds}s")
    if blocked_domains:
        blocker.apply_blocks(blocked_domains)
    killed = apps.kill_blocked_apps(blocked_apps)
    if killed:
        _log(f"Killed blocked apps: {', '.join(killed)}")

    session.create_session(
        profile_name=schedule.profile,
        duration_seconds=remaining_seconds,
        blocked_domains=blocked_domains,
        blocked_apps=blocked_apps,
    )
    _log(f"Session created for schedule '{name}'")

    # Mark as triggered today
    state[name] = today_str
    _save_schedule_state(state)


def _setup_signal_handlers() -> None:
    """Ignore SIGTERM/SIGINT during active sessions so launchctl bootout can't stop us.

    SIGKILL can't be caught, but KeepAlive in the plist will restart us immediately.
    """
    def _signal_handler(signum: int, frame: object) -> None:
        sess = session.load_session()
        if sess and sess.verify() and not sess.is_expired:
            _log(f"Ignoring signal {signum} — active session in progress")
            return
        # No active session — allow termination
        _log(f"Received signal {signum} — no active session, exiting")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


def watchdog_loop() -> None:
    """Main watchdog loop — runs every WATCHDOG_INTERVAL seconds."""
    _setup_signal_handlers()
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

                # Check if any schedule should auto-start a session
                _check_schedules()

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
