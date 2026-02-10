"""macOS menu bar status app — shows live focus session countdown."""

from __future__ import annotations

import math

import rumps

from lockin.session import get_active_session
from lockin.ui import format_duration

POLL_INTERVAL = 1  # seconds


class LockinMenuBar(rumps.App):
    """Menu bar app that displays the current focus session status."""

    def __init__(self):
        super().__init__("Lockin", title="LI", quit_button=None)

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
            self.title = "LI"
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

        self.title = f"LI {format_duration(remaining)}"
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
    LockinMenuBar().run()


if __name__ == "__main__":
    main()
