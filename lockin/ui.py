"""Rich display components for the CLI — menus, prompts, and live countdown."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from lockin.config import Config, Profile, Schedule
    from lockin.presets import Preset
    from lockin.session import Session

console = Console()
error_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs:
        parts.append(f"{secs}s")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Static display functions (unchanged from v0.1)
# ---------------------------------------------------------------------------


def show_status(session: Session | None) -> None:
    """Display current session status."""
    if session is None:
        panel = Panel(
            "[dim]No active focus session.[/dim]\n\n"
            "Start one with: [bold]sudo lockin start <profile> --duration 2h[/bold]",
            title="[bold]Lockin Status[/bold]",
            border_style="dim",
        )
        console.print(panel)
        return

    remaining = session.remaining_seconds
    elapsed = session.elapsed_seconds
    progress = min(elapsed / session.duration_seconds, 1.0) if session.duration_seconds > 0 else 1.0

    bar_width = 30
    filled = int(bar_width * progress)
    bar = "[green]" + "\u2588" * filled + "[/green]" + "[dim]\u2591[/dim]" * (bar_width - filled)

    domains_count = len(session.blocked_domains)
    apps_count = len(session.blocked_apps)

    content = (
        f"[bold green]Session Active[/bold green]\n\n"
        f"  Profile:   [bold]{session.profile_name}[/bold]\n"
        f"  Remaining: [bold yellow]{format_duration(remaining)}[/bold yellow]\n"
        f"  Progress:  {bar} {math.floor(progress * 100)}%\n"
        f"  Blocking:  [cyan]{domains_count}[/cyan] domains, [cyan]{apps_count}[/cyan] apps\n"
    )

    panel = Panel(content, title="[bold]Lockin Status[/bold]", border_style="green")
    console.print(panel)


def show_presets(presets: list[Preset]) -> None:
    """Display built-in presets."""
    table = Table(title="Built-in Presets", show_lines=True)
    table.add_column("Name", style="bold cyan", min_width=15)
    table.add_column("Description", style="dim")
    table.add_column("Domains", style="white")
    table.add_column("Apps", style="yellow")

    for preset in presets:
        domains_str = ", ".join(preset.domains)
        apps_str = ", ".join(preset.apps) if preset.apps else "[dim]none[/dim]"
        table.add_row(preset.name, preset.description, domains_str, apps_str)

    console.print(table)


def show_profiles(profiles: dict[str, Profile]) -> None:
    """Display all profiles."""
    if not profiles:
        console.print("[dim]No profiles configured yet.[/dim]")
        return

    table = Table(title="Profiles", show_lines=True)
    table.add_column("Name", style="bold cyan", min_width=12)
    table.add_column("Presets", style="green")
    table.add_column("Custom Sites", style="white")
    table.add_column("Apps", style="yellow")

    for name, profile in profiles.items():
        presets_str = ", ".join(profile.presets) if profile.presets else "[dim]none[/dim]"
        sites_str = ", ".join(profile.custom_sites) if profile.custom_sites else "[dim]none[/dim]"
        apps_str = ", ".join(profile.blocked_apps) if profile.blocked_apps else "[dim]none[/dim]"
        table.add_row(name, presets_str, sites_str, apps_str)

    console.print(table)


def show_profile_detail(profile: Profile) -> None:
    """Display a single profile in detail."""
    domains = profile.resolve_domains()
    apps = profile.resolve_apps()

    content = (
        f"  Presets:      [green]{', '.join(profile.presets) or 'none'}[/green]\n"
        f"  Custom Sites: [white]{', '.join(profile.custom_sites) or 'none'}[/white]\n"
        f"  Extra Apps:   [yellow]{', '.join(profile.blocked_apps) or 'none'}[/yellow]\n"
        f"\n"
        f"  [dim]Resolved \u2192 {len(domains)} domains, {len(apps)} apps[/dim]"
    )

    panel = Panel(content, title=f"[bold]Profile: {profile.name}[/bold]", border_style="cyan")
    console.print(panel)


def show_schedules(schedules: dict[str, Schedule]) -> None:
    """Display all schedules."""
    if not schedules:
        console.print("[dim]No schedules configured yet.[/dim]")
        return

    table = Table(title="Schedules", show_lines=True)
    table.add_column("Name", style="bold cyan")
    table.add_column("Profile", style="green")
    table.add_column("Days", style="white")
    table.add_column("Start", style="yellow")
    table.add_column("Duration", style="magenta")

    for name, schedule in schedules.items():
        days_str = ", ".join(schedule.days)
        table.add_row(
            name,
            schedule.profile,
            days_str,
            schedule.start_time,
            f"{schedule.duration_minutes}m",
        )

    console.print(table)


def show_apps(apps: list[str]) -> None:
    """Display detected macOS apps."""
    table = Table(title=f"Detected macOS Apps ({len(apps)})")
    table.add_column("#", style="dim", width=4)
    table.add_column("App Name", style="bold")

    for i, app in enumerate(apps, 1):
        table.add_row(str(i), app)

    console.print(table)


def show_always_blocked(sites: list[str], apps: list[str]) -> None:
    """Display always-blocked items."""
    if not sites and not apps:
        console.print("[dim]No always-blocked items.[/dim]")
        return

    content = ""
    if sites:
        content += "[bold]Sites:[/bold]\n"
        for site in sites:
            content += f"  \u2022 {site}\n"
    if apps:
        content += "[bold]Apps:[/bold]\n"
        for app in apps:
            content += f"  \u2022 {app}\n"

    panel = Panel(content.rstrip(), title="[bold]Always Blocked[/bold]", border_style="red")
    console.print(panel)


def print_success(message: str) -> None:
    console.print(f"[bold green]\u2713[/bold green] {message}")


def print_error(message: str) -> None:
    error_console.print(f"[bold red]\u2717[/bold red] {message}")


def print_warning(message: str) -> None:
    console.print(f"[bold yellow]![/bold yellow] {message}")


def print_info(message: str) -> None:
    console.print(f"[bold blue]i[/bold blue] {message}")


# ---------------------------------------------------------------------------
# Interactive menu / prompt helpers  (new in v0.2)
# ---------------------------------------------------------------------------


def show_banner() -> None:
    """Print the Lockin welcome banner."""
    console.print(
        Panel(
            "[bold]Lockin[/bold] \u2014 Focus blocker for macOS\n"
            "[dim]Block distracting websites & apps so you can get work done.[/dim]",
            border_style="bright_blue",
        )
    )


def show_menu(title: str, options: list[tuple[str, str]]) -> str:
    """Display a numbered menu and return the user's choice key.

    *options* is a list of ``(key, description)`` pairs, e.g.
    ``[("1", "Start a Focus Session  \u2014  pick profile, duration, go")]``.

    Returns the key string chosen by the user.
    """
    console.print()
    console.print(f"[bold]{title}[/bold]")
    for key, desc in options:
        console.print(f"  [bold cyan][{key}][/bold cyan] {desc}")
    console.print()

    valid = {k for k, _ in options}
    while True:
        choice = Prompt.ask("[bold]Choose an option[/bold]", console=console).strip()
        if choice in valid:
            return choice
        print_error(f"Invalid choice '{choice}'. Enter one of: {', '.join(sorted(valid))}")


def prompt_text(label: str, default: str = "") -> str:
    """Prompt for a single line of text."""
    if default:
        return Prompt.ask(f"[bold]{label}[/bold]", default=default, console=console).strip()
    return Prompt.ask(f"[bold]{label}[/bold]", console=console).strip()


def prompt_confirm(label: str, default: bool = False) -> bool:
    """Yes/no confirmation prompt."""
    return Confirm.ask(f"[bold]{label}[/bold]", default=default, console=console)


def prompt_pick_numbers(label: str, max_val: int) -> list[int]:
    """Ask the user to pick numbers from 1..max_val (comma-separated).

    Returns a sorted, deduplicated list of valid integers (1-based).
    An empty input returns an empty list.
    """
    raw = Prompt.ask(f"[bold]{label}[/bold] [dim](comma-separated, or Enter to skip)[/dim]", default="", console=console).strip()
    if not raw:
        return []
    nums: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            print_warning(f"Ignoring non-number '{part}'")
            continue
        if 1 <= n <= max_val:
            nums.append(n)
        else:
            print_warning(f"Ignoring out-of-range number {n}")
    return sorted(set(nums))


def show_numbered_list(title: str, items: list[str]) -> None:
    """Print a numbered list with a title."""
    console.print(f"\n[bold]{title}[/bold]")
    for i, item in enumerate(items, 1):
        console.print(f"  [bold cyan][{i}][/bold cyan] {item}")
    console.print()


def show_summary_panel(title: str, lines: list[str], border: str = "cyan") -> None:
    """Show a summary panel with the given lines."""
    content = "\n".join(f"  {line}" for line in lines)
    console.print(Panel(content, title=f"[bold]{title}[/bold]", border_style=border))


# ---------------------------------------------------------------------------
# Live countdown display
# ---------------------------------------------------------------------------


def live_countdown(session: Session) -> None:
    """Show a live-updating countdown for the active session.

    Refreshes once per second.  Ctrl+C cleanly exits the display
    (the session continues in the background).
    """
    console.print()
    print_info("Live countdown \u2014 press [bold]Ctrl+C[/bold] to hide (session continues in background)")
    console.print()

    try:
        with Live(console=console, refresh_per_second=1, transient=False) as live:
            while True:
                remaining = session.remaining_seconds
                if remaining <= 0:
                    live.update(_countdown_panel(session))
                    break
                live.update(_countdown_panel(session))
                time.sleep(1)
    except KeyboardInterrupt:
        console.print()
        print_info("Countdown hidden. Session continues in background.")
        return

    # Session has ended
    console.print()
    print_success("Focus session complete! Great work.")


def _countdown_panel(session: Session) -> Panel:
    """Build the Rich panel for the live countdown."""
    remaining = session.remaining_seconds
    elapsed = session.elapsed_seconds
    total = session.duration_seconds
    progress = min(elapsed / total, 1.0) if total > 0 else 1.0

    bar_width = 40
    filled = int(bar_width * progress)
    bar = "[green]" + "\u2588" * filled + "[/green]" + "[dim]\u2591[/dim]" * (bar_width - filled)

    domains_count = len(session.blocked_domains)
    apps_count = len(session.blocked_apps)

    if remaining <= 0:
        status = "[bold green]Complete![/bold green]"
    else:
        status = "[bold green]Active[/bold green]"

    content = (
        f"  Status:    {status}\n"
        f"  Profile:   [bold]{session.profile_name}[/bold]\n"
        f"  Remaining: [bold yellow]{format_duration(remaining)}[/bold yellow]\n"
        f"  Progress:  {bar} {math.floor(progress * 100)}%\n"
        f"  Blocking:  [cyan]{domains_count}[/cyan] domains, [cyan]{apps_count}[/cyan] apps"
    )

    border = "green" if remaining > 0 else "bright_green"
    return Panel(content, title="[bold]Focus Session[/bold]", border_style=border)
