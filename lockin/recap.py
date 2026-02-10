"""Analytics display for activity tracking — daily and weekly recaps."""

from __future__ import annotations

from datetime import date, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lockin.activity_db import (
    query_daily_summary,
    query_top_apps,
    query_top_domains,
    query_weekly_summary,
)
from lockin.ui import format_duration

console = Console()

_CATEGORY_COLORS = {
    "productive": "green",
    "neutral": "yellow",
    "distracting": "red",
}


def get_productivity_score(productive: float, neutral: float, distracting: float) -> float:
    """Calculate productivity score (0-100).

    Formula: (productive + 0.5 * neutral) / total * 100
    """
    total = productive + neutral + distracting
    if total == 0:
        return 0.0
    return (productive + 0.5 * neutral) / total * 100


def _build_color_bar(productive: float, neutral: float, distracting: float, width: int = 40) -> Text:
    """Build a colored proportion bar."""
    total = productive + neutral + distracting
    if total == 0:
        return Text("\u2591" * width, style="dim")

    green_w = max(1, round(productive / total * width)) if productive > 0 else 0
    yellow_w = max(1, round(neutral / total * width)) if neutral > 0 else 0
    red_w = width - green_w - yellow_w
    if red_w < 0:
        yellow_w += red_w
        red_w = 0

    bar = Text()
    bar.append("\u2588" * green_w, style="green")
    bar.append("\u2588" * yellow_w, style="yellow")
    bar.append("\u2588" * red_w, style="red")
    return bar


def show_daily_recap(target_date: date | None = None) -> None:
    """Show a Rich-formatted daily recap."""
    if target_date is None:
        target_date = date.today()

    summary = query_daily_summary(target_date)
    top_apps = query_top_apps(target_date)
    top_domains = query_top_domains(target_date)

    if not summary:
        console.print(f"[dim]No activity data for {target_date}.[/dim]")
        return

    # Calculate category totals
    cat_totals: dict[str, float] = {"productive": 0, "neutral": 0, "distracting": 0}
    for row in summary:
        cat = row.get("category", "neutral")
        secs = row.get("total_seconds", 0) or 0
        if cat in cat_totals:
            cat_totals[cat] += secs

    total_seconds = sum(cat_totals.values())
    score = get_productivity_score(cat_totals["productive"], cat_totals["neutral"], cat_totals["distracting"])

    # Header info
    bar = _build_color_bar(cat_totals["productive"], cat_totals["neutral"], cat_totals["distracting"])
    score_color = "green" if score >= 70 else ("yellow" if score >= 40 else "red")

    header_lines = Text()
    header_lines.append(f"  Total tracked: ")
    header_lines.append(format_duration(total_seconds), style="bold")
    header_lines.append(f"    Score: ")
    header_lines.append(f"{score:.0f}/100", style=f"bold {score_color}")
    header_lines.append("\n  ")
    header_lines.append_text(bar)
    header_lines.append("\n  ")
    header_lines.append(f"\u2588 {format_duration(cat_totals['productive'])}", style="green")
    header_lines.append("  ")
    header_lines.append(f"\u2588 {format_duration(cat_totals['neutral'])}", style="yellow")
    header_lines.append("  ")
    header_lines.append(f"\u2588 {format_duration(cat_totals['distracting'])}", style="red")

    date_str = target_date.strftime("%A, %B %d, %Y")
    console.print(Panel(header_lines, title=f"[bold]Activity Recap \u2014 {date_str}[/bold]", border_style="bright_blue"))

    # Top apps table
    if top_apps:
        table = Table(title="Top Apps", show_lines=False, pad_edge=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("App", style="bold", min_width=20)
        table.add_column("Time", min_width=10)
        table.add_column("Category", min_width=12)

        for i, row in enumerate(top_apps, 1):
            secs = row.get("total_seconds", 0) or 0
            cat = row.get("category", "neutral")
            color = _CATEGORY_COLORS.get(cat, "white")
            table.add_row(
                str(i),
                row.get("app_name", "?"),
                format_duration(secs),
                f"[{color}]{cat}[/{color}]",
            )
        console.print(table)

    # Top domains table
    if top_domains:
        table = Table(title="Top Domains", show_lines=False, pad_edge=False)
        table.add_column("#", style="dim", width=3)
        table.add_column("Domain", style="bold", min_width=25)
        table.add_column("Time", min_width=10)
        table.add_column("Category", min_width=12)

        for i, row in enumerate(top_domains, 1):
            secs = row.get("total_seconds", 0) or 0
            cat = row.get("category", "neutral")
            color = _CATEGORY_COLORS.get(cat, "white")
            table.add_row(
                str(i),
                row.get("domain", "?"),
                format_duration(secs),
                f"[{color}]{cat}[/{color}]",
            )
        console.print(table)


def show_weekly_recap() -> None:
    """Show per-day breakdown for the last 7 days."""
    today = date.today()
    start = today - timedelta(days=6)

    weekly = query_weekly_summary(start, today)

    if not weekly:
        console.print("[dim]No activity data for the past week.[/dim]")
        return

    # Organize by day
    day_data: dict[str, dict[str, float]] = {}
    for d in range(7):
        day = (start + timedelta(days=d)).isoformat()
        day_data[day] = {"productive": 0, "neutral": 0, "distracting": 0}

    for row in weekly:
        day = row.get("day", "")
        cat = row.get("category", "neutral")
        secs = row.get("total_seconds", 0) or 0
        if day in day_data and cat in day_data[day]:
            day_data[day][cat] += secs

    table = Table(title="Weekly Activity Recap", show_lines=True)
    table.add_column("Day", style="bold", min_width=12)
    table.add_column("Total", min_width=8)
    table.add_column("Productive", style="green", min_width=10)
    table.add_column("Neutral", style="yellow", min_width=10)
    table.add_column("Distracting", style="red", min_width=10)
    table.add_column("Score", min_width=6)

    totals = {"productive": 0.0, "neutral": 0.0, "distracting": 0.0}

    for day_str, cats in sorted(day_data.items()):
        day_date = date.fromisoformat(day_str)
        day_label = day_date.strftime("%a %m/%d")
        total = sum(cats.values())
        score = get_productivity_score(cats["productive"], cats["neutral"], cats["distracting"])
        score_color = "green" if score >= 70 else ("yellow" if score >= 40 else "red")

        for cat in totals:
            totals[cat] += cats[cat]

        if total == 0:
            table.add_row(day_label, "[dim]--[/dim]", "", "", "", "")
        else:
            table.add_row(
                day_label,
                format_duration(total),
                format_duration(cats["productive"]) if cats["productive"] else "",
                format_duration(cats["neutral"]) if cats["neutral"] else "",
                format_duration(cats["distracting"]) if cats["distracting"] else "",
                f"[{score_color}]{score:.0f}[/{score_color}]",
            )

    # Totals row
    grand_total = sum(totals.values())
    overall_score = get_productivity_score(totals["productive"], totals["neutral"], totals["distracting"])
    sc = "green" if overall_score >= 70 else ("yellow" if overall_score >= 40 else "red")
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{format_duration(grand_total)}[/bold]",
        format_duration(totals["productive"]) if totals["productive"] else "",
        format_duration(totals["neutral"]) if totals["neutral"] else "",
        format_duration(totals["distracting"]) if totals["distracting"] else "",
        f"[bold {sc}]{overall_score:.0f}[/bold {sc}]",
    )

    console.print(table)


def get_quick_summary(target_date: date | None = None) -> str:
    """Return a one-line summary string suitable for a notification."""
    if target_date is None:
        target_date = date.today()

    summary = query_daily_summary(target_date)
    if not summary:
        return "No activity tracked today."

    cat_totals: dict[str, float] = {"productive": 0, "neutral": 0, "distracting": 0}
    for row in summary:
        cat = row.get("category", "neutral")
        secs = row.get("total_seconds", 0) or 0
        if cat in cat_totals:
            cat_totals[cat] += secs

    total = sum(cat_totals.values())
    score = get_productivity_score(cat_totals["productive"], cat_totals["neutral"], cat_totals["distracting"])

    return (
        f"Tracked: {format_duration(total)} | "
        f"Score: {score:.0f}/100 | "
        f"P: {format_duration(cat_totals['productive'])} "
        f"N: {format_duration(cat_totals['neutral'])} "
        f"D: {format_duration(cat_totals['distracting'])}"
    )
