"""macOS app detection and process killing."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import psutil

APP_DIRS = [
    Path("/Applications"),
    Path.home() / "Applications",
]


def list_installed_apps() -> list[str]:
    """Scan /Applications and ~/Applications for .app bundles."""
    apps: list[str] = []
    for app_dir in APP_DIRS:
        if not app_dir.exists():
            continue
        for entry in sorted(app_dir.iterdir()):
            if entry.suffix == ".app" and entry.is_dir():
                apps.append(entry.stem)
    return apps


def _quit_app_graceful(app_name: str) -> bool:
    """Try to quit an app gracefully via osascript."""
    result = subprocess.run(
        ["osascript", "-e", f'quit app "{app_name}"'],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _kill_app_forceful(app_name: str) -> bool:
    """Forcefully kill an app via killall."""
    result = subprocess.run(
        ["killall", app_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def kill_app(app_name: str) -> bool:
    """Kill a running app — try graceful first, then forceful."""
    if _quit_app_graceful(app_name):
        return True
    return _kill_app_forceful(app_name)


def is_app_running(app_name: str) -> bool:
    """Check if an app is currently running."""
    app_name_lower = app_name.lower()
    for proc in psutil.process_iter(["name"]):
        try:
            proc_name = proc.info["name"]
            if proc_name and app_name_lower in proc_name.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def kill_blocked_apps(app_names: list[str]) -> list[str]:
    """Kill all blocked apps instantly via SIGKILL.

    Single pass over the process table, immediate kill — no graceful quit,
    no subprocess spawn.  Apps should never visibly open.
    """
    if not app_names:
        return []

    blocked_lower = {name.lower() for name in app_names}
    killed_names: set[str] = set()

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = proc.info["name"]
            if not proc_name:
                continue
            proc_name_lower = proc_name.lower()
            for blocked in blocked_lower:
                if blocked in proc_name_lower:
                    proc.send_signal(signal.SIGKILL)
                    killed_names.add(proc_name)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            continue

    return sorted(killed_names)
