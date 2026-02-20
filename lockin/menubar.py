"""macOS menu bar status app — shows live focus session countdown."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import rumps

from lockin.session import get_active_session
from lockin.ui import format_duration

POLL_INTERVAL = 1  # seconds
PID_FILE = Path("/tmp/lockin-menubar.pid")


def _create_sf_icon(symbol_name: str):
    """Create a template NSImage from an SF Symbol name."""
    try:
        from AppKit import NSImage

        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol_name, "Lockin"
        )
        if icon:
            icon.setTemplate_(True)
            return icon
    except Exception:
        pass
    return None


def _hide_dock_icon():
    """Hide the Python rocketship from the Dock."""
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory

        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def _acquire_pid_lock() -> bool:
    """Write our PID to a lock file. Returns False if another instance is alive."""
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if that process is still alive
            os.kill(old_pid, 0)
            return False  # still running
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            pass  # stale PID file
    PID_FILE.write_text(str(os.getpid()))
    return True


def _release_pid_lock():
    """Remove the PID file on exit."""
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


class LockinMenuBar(rumps.App):
    """Menu bar app that displays the current focus session status."""

    def __init__(self):
        super().__init__("Lockin", title="lockin", quit_button=None)

        # Pre-create both icons
        self._icon_unlocked = _create_sf_icon("lock.open")
        self._icon_locked = _create_sf_icon("lock.fill")

        # Start with unlocked icon
        if self._icon_unlocked:
            self._icon = self._icon_unlocked

        self._session_active = False

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

    def _set_icon(self, nsimage):
        """Update the status bar button image directly."""
        self._icon = nsimage
        try:
            self._nsapp.nsstatusitem.button().setImage_(nsimage)
        except (AttributeError, TypeError):
            pass

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
            if self._session_active:
                self._session_active = False
                if self._icon_unlocked:
                    self._set_icon(self._icon_unlocked)
            self.title = "lockin"
            self.menu.clear()
            self.menu = [
                rumps.MenuItem("No active session", callback=None),
                None,
                rumps.MenuItem("Today's Recap", callback=self._show_recap),
                rumps.MenuItem("Quit", callback=self._quit),
            ]
            return

        if not self._session_active:
            self._session_active = True
            if self._icon_locked:
                self._set_icon(self._icon_locked)

        remaining = session.remaining_seconds
        elapsed = session.elapsed_seconds
        total = session.duration_seconds
        progress = min(elapsed / total, 1.0) if total > 0 else 1.0
        percent = math.floor(progress * 100)

        domains_count = len(session.blocked_domains)
        apps_count = len(session.blocked_apps)

        self.title = f"lockedin {format_duration(remaining)}"
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
        _release_pid_lock()
        rumps.quit_application()


def main():
    """Entry point for the lockin-menubar command."""
    _hide_dock_icon()

    if not _acquire_pid_lock():
        print("lockin-menubar is already running.")
        sys.exit(0)

    try:
        LockinMenuBar().run()
    finally:
        _release_pid_lock()


if __name__ == "__main__":
    main()
