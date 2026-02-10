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
        self.menu = [
            rumps.MenuItem("No active session", callback=None),
            None,  # separator
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self.timer = rumps.Timer(self._tick, POLL_INTERVAL)
        self.timer.start()

    def _tick(self, _sender):
        """Poll session state and update the menu bar."""
        session = get_active_session()

        if session is None:
            self.title = "LI"
            self.menu.clear()
            self.menu = [
                rumps.MenuItem("No active session", callback=None),
                None,
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
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _quit(self, _sender):
        rumps.quit_application()


def main():
    """Entry point for the lockin-menubar command."""
    LockinMenuBar().run()


if __name__ == "__main__":
    main()
