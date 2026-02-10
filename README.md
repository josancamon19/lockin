# Lockin

Focus blocker for macOS. Blocks distracting websites and apps so you can get work done.

```
lockin
```

```
╭──────────────────────────────────────╮
│            LOCKIN v0.3.0             │
│      Focus when it matters most      │
╰──────────────────────────────────────╯

Main Menu
  [1] Start a Focus Session
  [2] Manage Profiles
  [3] Manage Schedules
  [4] Always-Blocked Sites
  [5] View Presets
  [6] Activity Recap
  [7] Settings & Info
  [0] Exit
```

## How it works

- Blocks websites via `/etc/hosts` — works across every browser, no extensions
- Kills distracting apps on launch (Discord, Spotify, etc.)
- Sessions are **tamper-resistant** — once started, they can't be stopped
- A launchd watchdog re-applies blocks every 3 seconds, survives reboots
- Tracks your activity in the background — apps, browser URLs, productivity score
- Menu bar app shows live session countdown and runs the activity tracker
- Periodic screenshot capture (opt-in) for visual activity logging

## Install

Requires **macOS** and **Python 3.11+**.

```bash
pipx install lockin
```

## Setup

```bash
# Launch the interactive menu
lockin

# Or use CLI shortcuts
lockin --status          # Check active session
lockin --recap           # Today's productivity report
lockin --recap weekly    # Weekly summary
```

The interactive menu walks you through everything — creating profiles, starting sessions, configuring settings.

## Key concepts

**Presets** are built-in bundles of sites/apps by category (social, entertainment, news, gaming, communication).

**Profiles** combine presets with custom sites and apps into a blocking configuration.

**Sessions** activate a profile for a set duration. Once started, there's no stopping it.

```
Presets             Profile              Session
─────────           ────────             ────────
social       ─┐     "work"               2h focus
entertainment ┼──>  + slack.com   ────>  96 domains blocked
news         ─┘    + Slack app           3 apps killed
```

## Activity tracking

The menu bar app (`lockin-menubar`) tracks your activity in the background:

- Detects frontmost app and window title every second
- Extracts browser URLs via the Accessibility API
- Categorizes activity as productive / neutral / distracting
- Stores everything in a local SQLite database
- Optional periodic screenshots saved as compressed JPEGs

View your data anytime with `lockin --recap` or through the interactive menu.

## Tamper protection

| Attack | Mitigation |
|--------|------------|
| Edit `/etc/hosts` | Immutable flag; watchdog re-applies |
| Kill the watchdog | launchd auto-respawns it |
| Delete session file | Blocks become permanent |
| Modify session times | HMAC signature invalidates |
| Reboot | Session persists, daemon has `RunAtLoad` |

## Storage

- Config: `~/.config/lockin/config.json`
- Activity DB: `~/.config/lockin/activity.db`
- Screenshots: `~/.config/lockin/screenshots/`
- Sessions: `/var/lockin/session.json`

## License

MIT
