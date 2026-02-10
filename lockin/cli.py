"""Interactive terminal UI — replaces the old Typer-based CLI (v0.2)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lockin import __version__
from lockin.apps import list_installed_apps
from lockin.blocker import apply_blocks, remove_blocks
from lockin.config import Config, Profile, Schedule, load_config, resolve_blocked_lists, save_config
from lockin.daemon import install_daemon, is_daemon_installed, uninstall_daemon
from lockin.presets import PRESETS, list_presets
from lockin.session import (
    Session,
    create_session,
    delete_session,
    get_active_session,
    load_session,
)
from lockin.ui import (
    console,
    format_duration,
    live_countdown,
    print_error,
    print_info,
    print_success,
    print_warning,
    prompt_confirm,
    prompt_pick_numbers,
    prompt_text,
    show_always_blocked,
    show_banner,
    show_menu,
    show_numbered_list,
    show_presets,
    show_profile_detail,
    show_profiles,
    show_schedules,
    show_status,
    show_summary_panel,
)


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

def _parse_duration(duration_str: str) -> int | None:
    """Parse duration string like '2h', '30m', '1h30m', '90s' into seconds.

    Returns None on failure instead of raising.
    """
    pattern = r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
    match = re.fullmatch(pattern, duration_str.strip())
    if not match or not any(match.groups()):
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


# ---------------------------------------------------------------------------
# CLI shortcuts  (--version, --status, --start-session)
# ---------------------------------------------------------------------------

def _handle_argv() -> bool:
    """Handle CLI shortcut flags.  Returns True if a shortcut was handled."""
    args = sys.argv[1:]
    if not args:
        return False

    # --version / -v
    if args[0] in ("--version", "-v"):
        console.print(f"lockin v{__version__}")
        return True

    # --status
    if args[0] == "--status":
        session = load_session()
        if session and session.verify() and not session.is_expired:
            show_status(session)
        else:
            show_status(None)
        return True

    # --start-session <profile> --duration <dur>  (used by sudo re-exec)
    if args[0] == "--start-session":
        _handle_start_session_shortcut(args[1:])
        return True

    # --recap [daily|weekly] [--date YYYY-MM-DD]
    if args[0] == "--recap":
        _handle_recap_shortcut(args[1:])
        return True

    # Unknown flag — print help hint
    print_error(f"Unknown option: {args[0]}")
    console.print("[dim]Usage: lockin              (interactive menu)[/dim]")
    console.print("[dim]       lockin --version    (show version)[/dim]")
    console.print("[dim]       lockin --status     (show session status)[/dim]")
    console.print("[dim]       lockin --recap      (show activity recap)[/dim]")
    return True


def _handle_recap_shortcut(args: list[str]) -> None:
    """Process ``--recap [daily|weekly] [--date YYYY-MM-DD]``."""
    from datetime import date, timedelta

    from lockin.recap import show_daily_recap, show_weekly_recap

    mode = "daily"
    target_date = date.today()

    i = 0
    while i < len(args):
        if args[i] in ("daily", "weekly"):
            mode = args[i]
            i += 1
        elif args[i] == "--date" and i + 1 < len(args):
            try:
                target_date = date.fromisoformat(args[i + 1])
            except ValueError:
                print_error(f"Invalid date '{args[i + 1]}'. Use YYYY-MM-DD format.")
                return
            i += 2
        else:
            print_error(f"Unknown argument: {args[i]}")
            return

    if mode == "weekly":
        show_weekly_recap()
    else:
        show_daily_recap(target_date)


def _handle_start_session_shortcut(args: list[str]) -> None:
    """Process ``--start-session <profile> --duration <dur>`` (root only)."""
    if os.geteuid() != 0:
        print_error("--start-session requires root. This flag is used internally by sudo re-exec.")
        sys.exit(1)

    profile_name: str | None = None
    duration_str: str = "1h"
    i = 0
    while i < len(args):
        if args[i] == "--duration" and i + 1 < len(args):
            duration_str = args[i + 1]
            i += 2
        elif profile_name is None:
            profile_name = args[i]
            i += 1
        else:
            print_error(f"Unexpected argument: {args[i]}")
            sys.exit(1)

    if not profile_name:
        print_error("Missing profile name after --start-session.")
        sys.exit(1)

    duration_seconds = _parse_duration(duration_str)
    if duration_seconds is None:
        print_error(f"Invalid duration '{duration_str}'. Use format like: 2h, 30m, 1h30m")
        sys.exit(1)

    _do_start_session(profile_name, duration_seconds)


# ---------------------------------------------------------------------------
# Session start logic (shared by interactive flow and shortcut)
# ---------------------------------------------------------------------------

def _do_start_session(profile_name: str, duration_seconds: int) -> None:
    """Apply blocks and create a session.  Must be running as root."""
    active = get_active_session()
    if active:
        print_error(
            f"A session is already active (profile: {active.profile_name}, "
            f"remaining: {format_duration(active.remaining_seconds)}). Cannot start another."
        )
        sys.exit(1)

    config = load_config()
    profile = config.profiles.get(profile_name)
    if profile is None:
        print_error(f"Profile '{profile_name}' not found.")
        sys.exit(1)

    blocked_domains, blocked_apps = resolve_blocked_lists(profile, config.always_blocked)

    if not blocked_domains and not blocked_apps:
        print_warning("This profile has nothing to block. Add presets or custom sites first.")
        sys.exit(1)

    # Ensure daemon
    if not is_daemon_installed():
        print_warning("Watchdog daemon is not installed. Installing now...")
        if not install_daemon():
            print_error("Failed to install watchdog daemon.")
            sys.exit(1)
        print_success("Watchdog daemon installed.")

    # Apply blocks
    if blocked_domains:
        if not apply_blocks(blocked_domains):
            print_error("Failed to apply website blocks. Are you running as root?")
            sys.exit(1)

    # Kill blocked apps
    from lockin.apps import kill_blocked_apps

    killed = kill_blocked_apps(blocked_apps)
    if killed:
        print_info(f"Killed blocked apps: {', '.join(killed)}")

    # Create signed session
    sess = create_session(
        profile_name=profile_name,
        duration_seconds=duration_seconds,
        blocked_domains=blocked_domains,
        blocked_apps=blocked_apps,
    )

    print_success("Focus session started!")
    print_info(f"Profile: {profile_name}")
    print_info(f"Duration: {format_duration(duration_seconds)}")
    print_info(f"Blocking: {len(blocked_domains)} domains, {len(blocked_apps)} apps")
    print_warning("This session cannot be stopped until the timer expires.")

    # Show live countdown
    live_countdown(sess)


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

MAIN_MENU_OPTIONS = [
    ("1", "Start a Focus Session  \u2014  pick profile, duration, go"),
    ("2", "Manage Profiles        \u2014  create / view / edit / delete"),
    ("3", "Manage Schedules       \u2014  create / list / delete"),
    ("4", "Always-Blocked Sites   \u2014  add / remove domains"),
    ("5", "View Presets           \u2014  show built-in categories (read-only)"),
    ("6", "Activity Recap         \u2014  daily / weekly productivity reports"),
    ("7", "Settings & Info        \u2014  daemon status, installed apps, version"),
    ("0", "Exit"),
]


def _main_menu() -> None:
    """Run the interactive main menu loop."""
    show_banner()

    while True:
        choice = show_menu("Main Menu", MAIN_MENU_OPTIONS)
        if choice == "1":
            _flow_start_session()
        elif choice == "2":
            _flow_manage_profiles()
        elif choice == "3":
            _flow_manage_schedules()
        elif choice == "4":
            _flow_always_blocked()
        elif choice == "5":
            _flow_view_presets()
        elif choice == "6":
            _flow_activity_recap()
        elif choice == "7":
            _flow_settings()
        elif choice == "0":
            console.print("[dim]Goodbye![/dim]")
            break


# ---------------------------------------------------------------------------
# Flow: Start a Focus Session
# ---------------------------------------------------------------------------

DURATION_OPTIONS = [
    ("1", "30 minutes"),
    ("2", "1 hour"),
    ("3", "2 hours"),
    ("4", "4 hours"),
    ("5", "Custom"),
    ("0", "Back"),
]

DURATION_MAP = {"1": "30m", "2": "1h", "3": "2h", "4": "4h"}


def _flow_start_session() -> None:
    config = load_config()

    if not config.profiles:
        print_warning("No profiles yet. Let's create one first.")
        _flow_create_profile()
        config = load_config()
        if not config.profiles:
            return

    # Pick profile
    profile_names = list(config.profiles.keys())
    show_numbered_list("Select a profile", profile_names)
    nums = prompt_pick_numbers("Profile number", len(profile_names))
    if not nums:
        return
    profile_name = profile_names[nums[0] - 1]
    profile = config.profiles[profile_name]

    # Show what this profile blocks
    show_profile_detail(profile)

    # Pick duration
    choice = show_menu("Session Duration", DURATION_OPTIONS)
    if choice == "0":
        return

    if choice == "5":
        raw = prompt_text("Enter duration (e.g. 1h30m, 45m, 2h)")
        duration_seconds = _parse_duration(raw)
        if duration_seconds is None:
            print_error(f"Invalid duration '{raw}'.")
            return
    else:
        duration_seconds = _parse_duration(DURATION_MAP[choice])
        assert duration_seconds is not None

    duration_display = format_duration(duration_seconds)
    domains = profile.resolve_domains()
    apps = profile.resolve_apps()

    # Summary + warning
    show_summary_panel(
        "Session Summary",
        [
            f"Profile:   [bold]{profile_name}[/bold]",
            f"Duration:  [bold yellow]{duration_display}[/bold yellow]",
            f"Blocking:  [cyan]{len(domains)}[/cyan] domains, [cyan]{len(apps)}[/cyan] apps",
        ],
        border="yellow",
    )
    print_warning("Once started, this session CANNOT be stopped until the timer expires.")

    if not prompt_confirm("Start session?"):
        print_info("Cancelled.")
        return

    # Need root — re-exec with sudo
    if os.geteuid() != 0:
        print_info("Requesting administrator privileges...")
        python = sys.executable
        os.execvp("sudo", [
            "sudo", python, "-m", "lockin.cli",
            "--start-session", profile_name,
            "--duration", DURATION_MAP.get(choice, raw if choice == "5" else "1h"),
        ])
        # execvp does not return
    else:
        _do_start_session(profile_name, duration_seconds)


# ---------------------------------------------------------------------------
# Flow: Manage Profiles
# ---------------------------------------------------------------------------

PROFILE_MENU = [
    ("1", "Create a new profile"),
    ("2", "View all profiles"),
    ("3", "View profile details"),
    ("4", "Edit a profile"),
    ("5", "Delete a profile"),
    ("0", "Back"),
]


def _flow_manage_profiles() -> None:
    while True:
        choice = show_menu("Manage Profiles", PROFILE_MENU)
        if choice == "0":
            return
        elif choice == "1":
            _flow_create_profile()
        elif choice == "2":
            config = load_config()
            show_profiles(config.profiles)
        elif choice == "3":
            _flow_view_profile()
        elif choice == "4":
            _flow_edit_profile()
        elif choice == "5":
            _flow_delete_profile()


def _flow_create_profile() -> None:
    """Guided profile creation."""
    config = load_config()

    name = prompt_text("Profile name")
    if not name:
        print_error("Name cannot be empty.")
        return
    if name in config.profiles:
        print_error(f"Profile '{name}' already exists.")
        return

    # Pick presets
    preset_names = list(PRESETS.keys())
    show_numbered_list("Available presets", [
        f"{n}  \u2014  {PRESETS[n].description}" for n in preset_names
    ])
    picked_nums = prompt_pick_numbers("Select presets", len(preset_names))
    chosen_presets = [preset_names[i - 1] for i in picked_nums]

    # Custom sites
    custom_sites: list[str] = []
    if prompt_confirm("Add custom sites to block?"):
        console.print("[dim]Enter domains one at a time. Empty line to finish.[/dim]")
        while True:
            domain = prompt_text("Domain (or Enter to finish)", default="")
            if not domain:
                break
            custom_sites.append(domain)

    # Block apps
    blocked_apps: list[str] = []
    if prompt_confirm("Block any macOS apps?"):
        installed = list_installed_apps()
        if installed:
            show_numbered_list("Installed apps", installed)
            app_nums = prompt_pick_numbers("Select apps to block", len(installed))
            blocked_apps = [installed[i - 1] for i in app_nums]
        else:
            print_warning("No apps detected in /Applications.")

    # Summary
    show_summary_panel(
        f"New Profile: {name}",
        [
            f"Presets:      [green]{', '.join(chosen_presets) or 'none'}[/green]",
            f"Custom Sites: [white]{', '.join(custom_sites) or 'none'}[/white]",
            f"Blocked Apps: [yellow]{', '.join(blocked_apps) or 'none'}[/yellow]",
        ],
    )

    if not prompt_confirm("Save this profile?", default=True):
        print_info("Cancelled.")
        return

    profile = Profile(
        name=name,
        presets=chosen_presets,
        custom_sites=custom_sites,
        blocked_apps=blocked_apps,
    )
    config.profiles[name] = profile
    save_config(config)
    print_success(f"Profile '{name}' created.")


def _flow_view_profile() -> None:
    config = load_config()
    if not config.profiles:
        print_warning("No profiles to show.")
        return
    names = list(config.profiles.keys())
    show_numbered_list("Profiles", names)
    nums = prompt_pick_numbers("Profile number", len(names))
    if not nums:
        return
    show_profile_detail(config.profiles[names[nums[0] - 1]])


def _flow_edit_profile() -> None:
    config = load_config()
    if not config.profiles:
        print_warning("No profiles to edit.")
        return
    names = list(config.profiles.keys())
    show_numbered_list("Profiles", names)
    nums = prompt_pick_numbers("Profile number to edit", len(names))
    if not nums:
        return

    profile = config.profiles[names[nums[0] - 1]]
    show_profile_detail(profile)

    edit_menu = [
        ("1", "Add presets"),
        ("2", "Remove presets"),
        ("3", "Add custom sites"),
        ("4", "Remove custom sites"),
        ("5", "Add blocked apps"),
        ("6", "Remove blocked apps"),
        ("0", "Done editing"),
    ]

    while True:
        choice = show_menu(f"Edit Profile: {profile.name}", edit_menu)
        if choice == "0":
            break
        elif choice == "1":
            available = [p for p in PRESETS if p not in profile.presets]
            if not available:
                print_info("All presets already added.")
                continue
            show_numbered_list("Available presets", available)
            picked = prompt_pick_numbers("Select presets to add", len(available))
            for i in picked:
                profile.presets.append(available[i - 1])
                print_success(f"Added preset '{available[i - 1]}'.")
        elif choice == "2":
            if not profile.presets:
                print_info("No presets to remove.")
                continue
            show_numbered_list("Current presets", profile.presets)
            picked = prompt_pick_numbers("Select presets to remove", len(profile.presets))
            to_remove = [profile.presets[i - 1] for i in picked]
            for p in to_remove:
                profile.presets.remove(p)
                print_success(f"Removed preset '{p}'.")
        elif choice == "3":
            console.print("[dim]Enter domains one at a time. Empty line to finish.[/dim]")
            while True:
                domain = prompt_text("Domain (or Enter to finish)", default="")
                if not domain:
                    break
                if domain not in profile.custom_sites:
                    profile.custom_sites.append(domain)
                    print_success(f"Added site '{domain}'.")
                else:
                    print_warning(f"Site '{domain}' already in profile.")
        elif choice == "4":
            if not profile.custom_sites:
                print_info("No custom sites to remove.")
                continue
            show_numbered_list("Custom sites", profile.custom_sites)
            picked = prompt_pick_numbers("Select sites to remove", len(profile.custom_sites))
            to_remove = [profile.custom_sites[i - 1] for i in picked]
            for s in to_remove:
                profile.custom_sites.remove(s)
                print_success(f"Removed site '{s}'.")
        elif choice == "5":
            installed = list_installed_apps()
            if not installed:
                print_warning("No apps detected.")
                continue
            show_numbered_list("Installed apps", installed)
            picked = prompt_pick_numbers("Select apps to block", len(installed))
            for i in picked:
                app = installed[i - 1]
                if app not in profile.blocked_apps:
                    profile.blocked_apps.append(app)
                    print_success(f"Added app '{app}'.")
                else:
                    print_warning(f"App '{app}' already blocked.")
        elif choice == "6":
            if not profile.blocked_apps:
                print_info("No blocked apps to remove.")
                continue
            show_numbered_list("Blocked apps", profile.blocked_apps)
            picked = prompt_pick_numbers("Select apps to unblock", len(profile.blocked_apps))
            to_remove = [profile.blocked_apps[i - 1] for i in picked]
            for a in to_remove:
                profile.blocked_apps.remove(a)
                print_success(f"Removed app '{a}'.")

    save_config(config)
    print_success(f"Profile '{profile.name}' updated.")
    show_profile_detail(profile)


def _flow_delete_profile() -> None:
    config = load_config()
    if not config.profiles:
        print_warning("No profiles to delete.")
        return

    # Block deletion if profile is in use
    active = get_active_session()

    names = list(config.profiles.keys())
    show_numbered_list("Profiles", names)
    nums = prompt_pick_numbers("Profile number to delete", len(names))
    if not nums:
        return
    name = names[nums[0] - 1]

    if active and active.profile_name == name:
        print_error(f"Cannot delete profile '{name}' \u2014 it's in use by the active session.")
        return

    if not prompt_confirm(f"Delete profile '{name}'?"):
        print_info("Cancelled.")
        return

    del config.profiles[name]
    save_config(config)
    print_success(f"Profile '{name}' deleted.")


# ---------------------------------------------------------------------------
# Flow: Manage Schedules
# ---------------------------------------------------------------------------

SCHEDULE_MENU = [
    ("1", "Create a new schedule"),
    ("2", "View all schedules"),
    ("3", "Delete a schedule"),
    ("0", "Back"),
]

DAY_MAP = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}

DAY_NAMES = list(DAY_MAP.keys())


def _flow_manage_schedules() -> None:
    while True:
        choice = show_menu("Manage Schedules", SCHEDULE_MENU)
        if choice == "0":
            return
        elif choice == "1":
            _flow_create_schedule()
        elif choice == "2":
            config = load_config()
            show_schedules(config.schedules)
        elif choice == "3":
            _flow_delete_schedule()


def _detect_timezone() -> str:
    """Detect the system IANA timezone name from /etc/localtime symlink."""
    try:
        from pathlib import Path

        link = Path("/etc/localtime").resolve()
        parts = link.parts
        idx = parts.index("zoneinfo")
        return "/".join(parts[idx + 1 :])
    except (ValueError, OSError):
        return ""


def _flow_create_schedule() -> None:
    config = load_config()

    if not config.profiles:
        print_warning("Create a profile first before setting up a schedule.")
        return

    name = prompt_text("Schedule name")
    if not name:
        print_error("Name cannot be empty.")
        return
    if name in config.schedules:
        print_error(f"Schedule '{name}' already exists.")
        return

    # Pick profile
    profile_names = list(config.profiles.keys())
    show_numbered_list("Profiles", profile_names)
    nums = prompt_pick_numbers("Profile number", len(profile_names))
    if not nums:
        return
    profile_name = profile_names[nums[0] - 1]

    # Pick days
    show_numbered_list("Days of the week", [
        f"{short} ({full})" for short, full in DAY_MAP.items()
    ])
    day_nums = prompt_pick_numbers("Select days", len(DAY_NAMES))
    if not day_nums:
        print_error("Must select at least one day.")
        return
    day_list = [list(DAY_MAP.values())[i - 1] for i in day_nums]

    # Start time
    start_time = prompt_text("Start time (HH:MM)", default="09:00")

    # Duration
    dur_str = prompt_text("Duration (e.g. 2h, 90m)", default="2h")
    dur_seconds = _parse_duration(dur_str)
    if dur_seconds is None:
        print_error(f"Invalid duration '{dur_str}'.")
        return
    duration_minutes = dur_seconds // 60

    tz_name = _detect_timezone()
    schedule = Schedule(
        name=name,
        profile=profile_name,
        days=day_list,
        start_time=start_time,
        duration_minutes=duration_minutes,
        timezone=tz_name,
    )
    config.schedules[name] = schedule
    save_config(config)
    tz_display = tz_name or "system default"
    print_success(f"Schedule '{name}' created (timezone: {tz_display}).")


def _flow_delete_schedule() -> None:
    config = load_config()
    if not config.schedules:
        print_warning("No schedules to delete.")
        return

    names = list(config.schedules.keys())
    show_numbered_list("Schedules", names)
    nums = prompt_pick_numbers("Schedule number to delete", len(names))
    if not nums:
        return
    name = names[nums[0] - 1]

    if not prompt_confirm(f"Delete schedule '{name}'?"):
        print_info("Cancelled.")
        return

    del config.schedules[name]
    save_config(config)
    print_success(f"Schedule '{name}' deleted.")


# ---------------------------------------------------------------------------
# Flow: Always-Blocked Sites
# ---------------------------------------------------------------------------

ALWAYS_BLOCKED_MENU = [
    ("1", "View always-blocked list"),
    ("2", "Add a domain"),
    ("3", "Remove a domain"),
    ("0", "Back"),
]


def _flow_always_blocked() -> None:
    while True:
        choice = show_menu("Always-Blocked Sites", ALWAYS_BLOCKED_MENU)
        if choice == "0":
            return
        elif choice == "1":
            config = load_config()
            show_always_blocked(config.always_blocked.sites, config.always_blocked.apps)
        elif choice == "2":
            domain = prompt_text("Domain to always block")
            if not domain:
                continue
            config = load_config()
            if domain in config.always_blocked.sites:
                print_warning(f"'{domain}' is already in the always-blocked list.")
            else:
                config.always_blocked.sites.append(domain)
                save_config(config)
                print_success(f"Added '{domain}' to always-blocked list.")
        elif choice == "3":
            config = load_config()
            if not config.always_blocked.sites:
                print_warning("No always-blocked sites to remove.")
                continue
            show_numbered_list("Always-blocked sites", config.always_blocked.sites)
            nums = prompt_pick_numbers("Site number to remove", len(config.always_blocked.sites))
            if not nums:
                continue
            domain = config.always_blocked.sites[nums[0] - 1]
            config.always_blocked.sites.remove(domain)
            save_config(config)
            print_success(f"Removed '{domain}' from always-blocked list.")


# ---------------------------------------------------------------------------
# Flow: View Presets
# ---------------------------------------------------------------------------

def _flow_view_presets() -> None:
    show_presets(list_presets())


# ---------------------------------------------------------------------------
# Flow: Activity Recap
# ---------------------------------------------------------------------------

RECAP_MENU = [
    ("1", "Today's recap"),
    ("2", "Yesterday's recap"),
    ("3", "Pick a date"),
    ("4", "Weekly summary"),
    ("0", "Back"),
]


def _flow_activity_recap() -> None:
    from datetime import date, timedelta

    from lockin.recap import show_daily_recap, show_weekly_recap

    while True:
        choice = show_menu("Activity Recap", RECAP_MENU)
        if choice == "0":
            return
        elif choice == "1":
            show_daily_recap(date.today())
        elif choice == "2":
            show_daily_recap(date.today() - timedelta(days=1))
        elif choice == "3":
            raw = prompt_text("Date (YYYY-MM-DD)")
            try:
                target = date.fromisoformat(raw)
                show_daily_recap(target)
            except ValueError:
                print_error(f"Invalid date '{raw}'. Use YYYY-MM-DD format.")
        elif choice == "4":
            show_weekly_recap()


# ---------------------------------------------------------------------------
# Flow: Settings & Info
# ---------------------------------------------------------------------------

def _build_settings_menu() -> list[tuple[str, str]]:
    granted = _check_accessibility()
    ax_status = "[green]ON[/green]" if granted else "[red]OFF[/red]"

    config = load_config()
    ss = config.screenshot_settings
    if ss.enabled:
        ss_label = f"[green]ON[/green] every {ss.interval_seconds}s, keep {ss.retention_days}d"
    else:
        ss_label = "[red]OFF[/red]"

    return [
        ("1", "Check daemon status"),
        ("2", "Install daemon"),
        ("3", "Uninstall daemon"),
        ("4", "List installed apps"),
        ("5", "Show version"),
        ("6", "Launch menu bar app"),
        ("7", "Install menu bar auto-start"),
        ("8", "Uninstall menu bar auto-start"),
        ("9", f"Accessibility permission [{ax_status}]  \u2014  needed for URL tracking"),
        ("s", f"Screenshot capture [{ss_label}]"),
        ("0", "Back"),
    ]


_LAUNCH_AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
_LAUNCH_AGENT_PLIST = _LAUNCH_AGENT_DIR / "com.lockin.menubar.plist"
_LAUNCH_AGENT_LABEL = "com.lockin.menubar"


def _menubar_plist_content() -> str:
    """Generate the Launch Agent plist XML for the menu bar app."""
    menubar_bin = shutil.which("lockin-menubar")
    if menubar_bin is None:
        menubar_bin = "lockin-menubar"
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{menubar_bin}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""


def _install_menubar_launch_agent() -> bool:
    """Install the Launch Agent plist for menu bar auto-start."""
    try:
        _LAUNCH_AGENT_DIR.mkdir(parents=True, exist_ok=True)
        _LAUNCH_AGENT_PLIST.write_text(_menubar_plist_content())
        subprocess.run(
            ["launchctl", "load", str(_LAUNCH_AGENT_PLIST)],
            check=True,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _uninstall_menubar_launch_agent() -> bool:
    """Uninstall the Launch Agent plist for menu bar auto-start."""
    try:
        if _LAUNCH_AGENT_PLIST.exists():
            subprocess.run(
                ["launchctl", "unload", str(_LAUNCH_AGENT_PLIST)],
                check=True,
                capture_output=True,
            )
            _LAUNCH_AGENT_PLIST.unlink()
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _is_menubar_launch_agent_installed() -> bool:
    """Check whether the menu bar Launch Agent plist exists."""
    return _LAUNCH_AGENT_PLIST.exists()


def _check_accessibility() -> bool:
    """Check accessibility permission status, returns True if granted."""
    try:
        from lockin.tracker import check_accessibility_permission
        return check_accessibility_permission()
    except Exception:
        return False


def _flow_grant_accessibility() -> None:
    """Guide the user through granting Accessibility permission."""
    if _check_accessibility():
        print_success("Accessibility permission is already granted.")
        return

    # Find the real Python binary that lockin-menubar uses
    python_bin = sys.executable
    try:
        real_path = Path(python_bin).resolve()
    except OSError:
        real_path = Path(python_bin)

    print_warning("Accessibility permission is NOT granted.")
    print_info("Activity tracking needs this permission to read browser URLs.")
    console.print()
    console.print("  [bold]Steps:[/bold]")
    console.print("  1. System Settings will open to Accessibility")
    console.print(f"  2. Click [bold]+[/bold] and press [bold]Cmd+Shift+G[/bold] to type a path")
    console.print(f"  3. Paste this path and add it:")
    console.print(f"     [bold cyan]{real_path}[/bold cyan]")
    console.print("  4. Make sure the toggle is [bold green]ON[/bold green]")
    console.print("  5. Restart the menu bar app")
    console.print()

    # Copy path to clipboard
    try:
        subprocess.run(
            ["pbcopy"],
            input=str(real_path).encode(),
            check=True,
        )
        print_success("Path copied to clipboard.")
    except (OSError, subprocess.CalledProcessError):
        pass

    # Open System Settings
    subprocess.Popen(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
    )


def _flow_screenshot_settings() -> None:
    """Configure periodic screenshot capture."""
    config = load_config()
    ss = config.screenshot_settings

    status = "[green]ON[/green]" if ss.enabled else "[red]OFF[/red]"
    show_summary_panel(
        "Screenshot Capture",
        [
            f"Status:    {status}",
            f"Interval:  [bold]{ss.interval_seconds}s[/bold]",
            f"Retention: [bold]{ss.retention_days} days[/bold]",
        ],
    )

    # Show storage usage
    from lockin.tracker import SCREENSHOTS_DIR

    if SCREENSHOTS_DIR.exists():
        total_size = 0
        file_count = 0
        for f in SCREENSHOTS_DIR.rglob("*.jpg"):
            total_size += f.stat().st_size
            file_count += 1
        if file_count > 0:
            if total_size >= 1024 * 1024:
                size_str = f"{total_size / (1024 * 1024):.1f} MB"
            else:
                size_str = f"{total_size / 1024:.0f} KB"
            print_info(f"Storage: {file_count} screenshots, {size_str}")

    menu = [
        ("1", "Enable" if not ss.enabled else "Disable"),
        ("2", "Set interval"),
        ("3", "Set retention"),
        ("0", "Back"),
    ]

    while True:
        choice = show_menu("Screenshot Settings", menu)
        if choice == "0":
            return
        elif choice == "1":
            ss.enabled = not ss.enabled
            config.screenshot_settings = ss
            save_config(config)
            state = "enabled" if ss.enabled else "disabled"
            print_success(f"Screenshot capture {state}.")
            menu[0] = ("1", "Enable" if not ss.enabled else "Disable")
        elif choice == "2":
            interval_menu = [
                ("1", "30 seconds"),
                ("2", "1 minute"),
                ("3", "2 minutes"),
                ("4", "5 minutes"),
                ("5", "Custom"),
                ("0", "Back"),
            ]
            ic = show_menu("Capture Interval", interval_menu)
            interval_map = {"1": 30, "2": 60, "3": 120, "4": 300}
            if ic in interval_map:
                ss.interval_seconds = interval_map[ic]
            elif ic == "5":
                raw = prompt_text("Interval in seconds (10-600)")
                try:
                    val = int(raw)
                    if 10 <= val <= 600:
                        ss.interval_seconds = val
                    else:
                        print_error("Must be between 10 and 600 seconds.")
                        continue
                except ValueError:
                    print_error("Invalid number.")
                    continue
            else:
                continue
            config.screenshot_settings = ss
            save_config(config)
            print_success(f"Interval set to {ss.interval_seconds}s.")
        elif choice == "3":
            retention_menu = [
                ("1", "7 days"),
                ("2", "14 days"),
                ("3", "30 days"),
                ("4", "Custom"),
                ("0", "Back"),
            ]
            rc = show_menu("Retention Period", retention_menu)
            retention_map = {"1": 7, "2": 14, "3": 30}
            if rc in retention_map:
                ss.retention_days = retention_map[rc]
            elif rc == "4":
                raw = prompt_text("Retention in days (1-365)")
                try:
                    val = int(raw)
                    if 1 <= val <= 365:
                        ss.retention_days = val
                    else:
                        print_error("Must be between 1 and 365 days.")
                        continue
                except ValueError:
                    print_error("Invalid number.")
                    continue
            else:
                continue
            config.screenshot_settings = ss
            save_config(config)
            print_success(f"Retention set to {ss.retention_days} days.")


def _flow_settings() -> None:
    while True:
        choice = show_menu("Settings & Info", _build_settings_menu())
        if choice == "0":
            return
        elif choice == "1":
            if is_daemon_installed():
                print_success("Watchdog daemon is installed.")
            else:
                print_warning("Watchdog daemon is NOT installed.")
        elif choice == "2":
            if os.geteuid() != 0:
                print_error("Installing the daemon requires root. Run: sudo lockin")
                continue
            if install_daemon():
                print_success("Watchdog daemon installed and loaded.")
            else:
                print_error("Failed to install the watchdog daemon.")
        elif choice == "3":
            if os.geteuid() != 0:
                print_error("Uninstalling the daemon requires root. Run: sudo lockin")
                continue
            active = get_active_session()
            if active:
                print_error("Cannot uninstall while a focus session is active.")
                continue
            if uninstall_daemon():
                print_success("Watchdog daemon uninstalled.")
            else:
                print_error("Failed to uninstall the watchdog daemon.")
        elif choice == "4":
            installed = list_installed_apps()
            from lockin.ui import show_apps

            show_apps(installed)
        elif choice == "5":
            console.print(f"lockin v{__version__}")
        elif choice == "6":
            menubar_bin = shutil.which("lockin-menubar")
            if menubar_bin is None:
                print_error("lockin-menubar not found. Reinstall the package to get the entry point.")
                continue
            subprocess.Popen([menubar_bin], start_new_session=True)
            print_success("Menu bar app launched.")
        elif choice == "7":
            if _is_menubar_launch_agent_installed():
                print_info("Menu bar auto-start is already installed.")
                continue
            if _install_menubar_launch_agent():
                print_success("Menu bar auto-start installed. It will launch at login.")
            else:
                print_error("Failed to install menu bar auto-start.")
        elif choice == "8":
            if not _is_menubar_launch_agent_installed():
                print_info("Menu bar auto-start is not installed.")
                continue
            if _uninstall_menubar_launch_agent():
                print_success("Menu bar auto-start removed.")
            else:
                print_error("Failed to remove menu bar auto-start.")
        elif choice == "9":
            _flow_grant_accessibility()
        elif choice == "s":
            _flow_screenshot_settings()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the ``lockin`` command."""
    # Handle CLI shortcuts first
    if _handle_argv():
        return

    # If there's an active session, show live countdown first
    session = load_session()
    if session and session.verify() and not session.is_expired:
        live_countdown(session)

    # Then show the interactive menu
    try:
        _main_menu()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
    except EOFError:
        console.print("\n[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
