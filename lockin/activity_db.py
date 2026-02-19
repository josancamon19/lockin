"""SQLite storage for activity tracking (~/.config/lockin/activity.db)."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".config" / "lockin" / "activity.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS activity_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    app_name     TEXT NOT NULL,
    bundle_id    TEXT,
    window_title TEXT,
    url          TEXT,
    domain       TEXT,
    category     TEXT NOT NULL DEFAULT 'neutral',
    preset_match TEXT
);
"""

_CREATE_SCREENSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS screenshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER,
    taken_at    TEXT NOT NULL,
    file_path   TEXT NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_activity_started ON activity_log(started_at);
"""

_CREATE_SCREENSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_screenshots_taken ON screenshots(taken_at);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_SCREENSHOTS_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.execute(_CREATE_SCREENSHOTS_INDEX)
        # Migration: add detail column if missing (safe for existing DBs)
        try:
            conn.execute("ALTER TABLE activity_log ADD COLUMN detail TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()
    finally:
        conn.close()


def insert_activity(
    started_at: str,
    app_name: str,
    bundle_id: str | None,
    window_title: str | None,
    url: str | None,
    domain: str | None,
    category: str,
    preset_match: str | None,
    detail: str | None = None,
) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO activity_log
               (started_at, app_name, bundle_id, window_title, url, domain, category, preset_match, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (started_at, app_name, bundle_id, window_title, url, domain, category, preset_match, detail),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def close_activity(row_id: int, ended_at: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE activity_log SET ended_at = ? WHERE id = ?",
            (ended_at, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def query_daily_summary(target_date: date) -> list[dict]:
    """Return rows for a given date, ordered by started_at.

    Each row has: app_name, domain, category, preset_match, total_seconds.
    Groups by (app_name, domain, category) and sums duration.
    """
    day_start = datetime(target_date.year, target_date.month, target_date.day).isoformat()
    day_end = (datetime(target_date.year, target_date.month, target_date.day) + timedelta(days=1)).isoformat()

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT app_name, domain, category, preset_match,
                      SUM(
                          CASE WHEN ended_at IS NOT NULL
                               THEN MAX(0, julianday(MIN(ended_at, ?)) - julianday(MAX(started_at, ?))) * 86400
                               ELSE MAX(0, julianday(?) - julianday(MAX(started_at, ?))) * 86400
                          END
                      ) as total_seconds
               FROM activity_log
               WHERE started_at < ? AND (ended_at > ? OR ended_at IS NULL)
               GROUP BY app_name, domain, category
               ORDER BY total_seconds DESC""",
            (day_end, day_start, datetime.now().isoformat(), day_start, day_end, day_start),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_top_apps(target_date: date, limit: int = 10) -> list[dict]:
    """Top apps by total time for a given date, split by detail (project/dir)."""
    day_start = datetime(target_date.year, target_date.month, target_date.day).isoformat()
    day_end = (datetime(target_date.year, target_date.month, target_date.day) + timedelta(days=1)).isoformat()

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT app_name, detail, category,
                      COUNT(*) as focus_count,
                      SUM(
                          CASE WHEN ended_at IS NOT NULL
                               THEN MAX(0, julianday(MIN(ended_at, ?)) - julianday(MAX(started_at, ?))) * 86400
                               ELSE MAX(0, julianday(?) - julianday(MAX(started_at, ?))) * 86400
                          END
                      ) as total_seconds
               FROM activity_log
               WHERE started_at < ? AND (ended_at > ? OR ended_at IS NULL)
               GROUP BY app_name, detail
               ORDER BY total_seconds DESC
               LIMIT ?""",
            (day_end, day_start, datetime.now().isoformat(), day_start, day_end, day_start, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_top_domains(target_date: date, limit: int = 10) -> list[dict]:
    """Top domains by total time for a given date (excludes NULL domains)."""
    day_start = datetime(target_date.year, target_date.month, target_date.day).isoformat()
    day_end = (datetime(target_date.year, target_date.month, target_date.day) + timedelta(days=1)).isoformat()

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT domain, category,
                      SUM(
                          CASE WHEN ended_at IS NOT NULL
                               THEN MAX(0, julianday(MIN(ended_at, ?)) - julianday(MAX(started_at, ?))) * 86400
                               ELSE MAX(0, julianday(?) - julianday(MAX(started_at, ?))) * 86400
                          END
                      ) as total_seconds
               FROM activity_log
               WHERE started_at < ? AND (ended_at > ? OR ended_at IS NULL)
                     AND domain IS NOT NULL
               GROUP BY domain
               ORDER BY total_seconds DESC
               LIMIT ?""",
            (day_end, day_start, datetime.now().isoformat(), day_start, day_end, day_start, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_weekly_summary(start: date, end: date) -> list[dict]:
    """Per-day category totals for a date range.

    Returns rows with: day, category, total_seconds.
    """
    range_start = datetime(start.year, start.month, start.day).isoformat()
    range_end = (datetime(end.year, end.month, end.day) + timedelta(days=1)).isoformat()

    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT date(started_at) as day, category,
                      SUM(
                          CASE WHEN ended_at IS NOT NULL
                               THEN MAX(0, julianday(MIN(ended_at, ?)) - julianday(MAX(started_at, ?))) * 86400
                               ELSE MAX(0, julianday(?) - julianday(MAX(started_at, ?))) * 86400
                          END
                      ) as total_seconds
               FROM activity_log
               WHERE started_at < ? AND (ended_at > ? OR ended_at IS NULL)
               GROUP BY day, category
               ORDER BY day, category""",
            (range_end, range_start, datetime.now().isoformat(), range_start, range_end, range_start),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -- Screenshot functions --


def insert_screenshot(activity_id: int | None, taken_at: str, file_path: str) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO screenshots (activity_id, taken_at, file_path) VALUES (?, ?, ?)",
            (activity_id, taken_at, file_path),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def delete_screenshots_before(cutoff_iso: str) -> list[str]:
    """Delete screenshot rows older than cutoff. Returns file_paths of deleted rows."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT file_path FROM screenshots WHERE taken_at < ?",
            (cutoff_iso,),
        ).fetchall()
        paths = [r["file_path"] for r in rows]
        if paths:
            conn.execute("DELETE FROM screenshots WHERE taken_at < ?", (cutoff_iso,))
            conn.commit()
        return paths
    finally:
        conn.close()


def query_screenshots_for_date(target_date: date) -> list[dict]:
    day_start = datetime(target_date.year, target_date.month, target_date.day).isoformat()
    day_end = (datetime(target_date.year, target_date.month, target_date.day) + timedelta(days=1)).isoformat()

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM screenshots WHERE taken_at >= ? AND taken_at < ? ORDER BY taken_at",
            (day_start, day_end),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fix_overnight_entries(dry_run: bool = True) -> list[dict]:
    """Find entries that cross midnight with duration > 1 hour and cap them.

    These are phantom entries caused by the system sleeping while an activity
    was open.  Each such entry gets its ended_at capped to started_at + 1 hour.

    Returns a list of dicts describing the affected rows.
    """
    conn = _connect()
    try:
        # Find entries where started_at and ended_at are on different dates
        # and the total duration exceeds 1 hour (3600 seconds).
        rows = conn.execute(
            """SELECT id, started_at, ended_at, app_name, domain, detail,
                      (julianday(ended_at) - julianday(started_at)) * 86400 as duration_seconds
               FROM activity_log
               WHERE ended_at IS NOT NULL
                     AND date(started_at) != date(ended_at)
                     AND (julianday(ended_at) - julianday(started_at)) * 86400 > 3600
               ORDER BY started_at"""
        ).fetchall()

        affected = []
        for row in rows:
            info = dict(row)
            started = datetime.fromisoformat(info["started_at"])
            capped_end = started + timedelta(hours=1)
            info["new_ended_at"] = capped_end.isoformat()
            info["old_ended_at"] = info["ended_at"]
            affected.append(info)

        if not dry_run and affected:
            for entry in affected:
                conn.execute(
                    "UPDATE activity_log SET ended_at = ? WHERE id = ?",
                    (entry["new_ended_at"], entry["id"]),
                )
            conn.commit()

        return affected
    finally:
        conn.close()
