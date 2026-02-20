"""macOS menu bar status app — shows live focus session countdown."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import psutil
import rumps

from lockin.session import get_active_session
from lockin.ui import format_duration

POLL_INTERVAL = 1  # seconds

# Resolve icon path relative to this file
_ASSETS_DIR = Path(__file__).parent / "assets"
_ICON_PATH = _ASSETS_DIR / "menubar_iconTemplate.png"


def _is_already_running() -> bool:
    """Check if another lockin-menubar process is already running."""
    my_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            # Match the actual entry point: "-m lockin.menubar" or a binary named lockin-menubar
            has_module = "-m" in cmdline and "lockin.menubar" in cmdline
            has_binary = any(arg.endswith("lockin-menubar") for arg in cmdline[:1])
            if has_module or has_binary:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


class LockinMenuBar(rumps.App):
    """Menu bar app that displays the current focus session status."""

    def __init__(self):
        icon = str(_ICON_PATH) if _ICON_PATH.exists() else None
        super().__init__("Lockin", icon=icon, title=None, quit_button=None, template=True)

        # Initialize activity tracker
        self._tracker = None
        try:
            from lockin.tracker import ActivityTracker, request_accessibility_permission

            request_accessibility_permission()
            self._tracker = ActivityTracker()
        except Exception:
            pass  # Tracker must never prevent menubar from starting

        self.menu = [
            rumps.MenuItem("No active session", callback=None),
            None,  # separator
            rumps.MenuItem("Today's Recap", callback=self._show_recap),
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self.timer = rumps.Timer(self._tick, POLL_INTERVAL)
        self.timer.start()

    def _tick(self, _sender):
        """Poll session state and update the menu bar."""
        # Activity tracking — must never crash the menubar
        if self._tracker is not None:
            try:
                self._tracker.poll()
            except Exception:
                pass

        session = get_active_session()

        if session is None:
            self.title = None
            self.menu.clear()
            self.menu = [
                rumps.MenuItem("No active session", callback=None),
                None,
                rumps.MenuItem("Today's Recap", callback=self._show_recap),
                rumps.MenuItem("Quit", callback=self._quit),
            ]
            return

        remaining = session.remaining_seconds
        elapsed = session.elapsed_seconds
        total = session.duration_seconds
        progress = min(elapsed / total, 1.0) if total > 0 else 1.0
        percent = math.floor(progress * 100)

        domains_count = len(session.blocked_domains)
        apps_count = len(session.blocked_apps)

        self.title = format_duration(remaining)
        self.menu.clear()
        self.menu = [
            rumps.MenuItem(f"Profile: {session.profile_name}", callback=None),
            rumps.MenuItem(f"Remaining: {format_duration(remaining)}", callback=None),
            rumps.MenuItem(f"Progress: {percent}%", callback=None),
            rumps.MenuItem(f"Blocking: {domains_count} domains, {apps_count} apps", callback=None),
            None,
            rumps.MenuItem("Today's Recap", callback=self._show_recap),
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _show_recap(self, _sender):
        """Show a notification with today's quick summary."""
        try:
            from lockin.recap import get_quick_summary

            summary = get_quick_summary()
            rumps.notification(
                title="Lockin - Today's Recap",
                subtitle="",
                message=summary,
            )
        except Exception:
            rumps.notification(
                title="Lockin",
                subtitle="",
                message="Could not load activity data.",
            )

    def _quit(self, _sender):
        if self._tracker is not None:
            try:
                self._tracker.shutdown()
            except Exception:
                pass
        rumps.quit_application()


def main():
    """Entry point for the lockin-menubar command."""
    if _is_already_running():
        print("lockin-menubar is already running.")
        sys.exit(0)
    LockinMenuBar().run()


if __name__ == "__main__":
    main()
