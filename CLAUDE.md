# Lockin — Development Notes

## After every code change
Always push and reinstall so the running menubar app picks up changes:
```bash
git add -A && git commit -m "..." && git push && uv pip install -e .
```

## Project structure
- `lockin/cli.py` — Interactive terminal UI, entry point `lockin`
- `lockin/menubar.py` — macOS menu bar app, entry point `lockin-menubar`
- `lockin/tracker.py` — Activity tracking (frontmost app, URLs via Accessibility API)
- `lockin/activity_db.py` — SQLite storage at `~/.config/lockin/activity.db`
- `lockin/categorizer.py` — Classify activity as productive/neutral/distracting
- `lockin/recap.py` — Daily/weekly analytics display
- `lockin/config.py` — Profile, schedule, always-blocked persistence
- `lockin/presets.py` — Built-in website/app category presets
- `lockin/daemon.py` — Watchdog daemon loop and launchd plist management
- `lockin/session.py` — Focus session management
- `lockin/blocker.py` — /etc/hosts blocker
- `lockin/apps.py` — macOS app detection and killing

## Package management
- Uses `uv` for dependency management
- `uv sync` to install deps, `uv pip install -e .` for editable install
- `uv run lockin` / `uv run lockin-menubar` to run without installing
