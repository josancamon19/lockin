# Lockin

A CLI focus blocker for macOS. Blocks distracting websites and apps at the network level so you can actually get work done.

- Blocks websites via `/etc/hosts` (not a browser extension — works across all browsers)
- Kills distracting app processes (Discord, Spotify, etc.)
- **Tamper-resistant**: sessions cannot be stopped early, even with `sudo`
- Enforced by a launchd watchdog daemon that re-applies blocks every 3 seconds
- Survives reboots, browser restarts, and DNS flushes

## Install

```bash
pip install lockin
```

Or with [pipx](https://pipx.pypa.io/) (recommended):

```bash
pipx install lockin
```

Requires **macOS** and **Python 3.11+**.

## Concepts

There are three layers: **presets**, **profiles**, and **sessions**.

```
Presets (built-in)       Profiles (you create)        Sessions (you start)
┌──────────────┐         ┌────────────────────┐        ┌──────────────────┐
│ social       │────┐    │ "work"             │        │ active session   │
│ entertainment│────┼───>│  presets: social,   │──────> │  profile: work   │
│ news         │    │    │    entertainment    │        │  duration: 2h    │
│ gaming       │    │    │  custom: slack.com  │        │  96 domains      │
└──────────────┘    │    │  apps: Slack        │        │  3 apps          │
                    │    └────────────────────┘        └──────────────────┘
                    │    ┌────────────────────┐
                    └───>│ "study"            │
                         │  presets: social,   │
                         │    news, gaming     │
                         └────────────────────┘
```

- **Presets** are built-in bundles of sites and apps grouped by category (social media, entertainment, etc.). You can't edit them — they're just building blocks.
- **Profiles** are blocking configs *you* create. A profile picks one or more presets and optionally adds custom sites/apps on top. Think of it as "what do I want blocked when I'm doing X?"
- **Sessions** are timed activations of a profile. Once started, a session is locked in — no stopping, no editing, no cheating.

## Quick Start

```bash
# 1. Create a profile that combines presets
lockin profile create work --preset social --preset entertainment

# 2. Start a 2-hour focus session with that profile
sudo lockin start work --duration 2h

# 3. Check remaining time
lockin
```

That's it. For the next 2 hours, social media and streaming sites are unreachable and Discord/Spotify get killed on launch.

## Presets

Built-in categories you can mix into profiles. Run `lockin preset` to see them:

| Preset | Sites | Apps |
|--------|-------|------|
| **social** | x.com, twitter.com, facebook.com, instagram.com, tiktok.com, reddit.com, threads.net, snapchat.com, linkedin.com | Discord |
| **entertainment** | youtube.com, netflix.com, twitch.tv, hulu.com, disneyplus.com, primevideo.com, spotify.com | Spotify |
| **communication** | whatsapp.com, gmail.com, superhuman.com | WhatsApp, Messages, Superhuman, Mail |
| **news** | news.ycombinator.com, cnn.com, bbc.com, nytimes.com, theguardian.com | — |
| **gaming** | steampowered.com, store.steampowered.com, epicgames.com, riotgames.com | Steam, Epic Games Launcher |

Each domain is also blocked with subdomain variants (www, m, api, mobile, app).

## Commands

### Profiles

Profiles define what to block. Combine presets with custom sites and apps:

```bash
# Block social + entertainment (presets only)
lockin profile create work --preset social --preset entertainment

# Block social + a custom site + an app
lockin profile create coding --preset social --site chatgpt.com --app Slack

# Block everything
lockin profile create lockdown --preset social --preset entertainment --preset news --preset gaming

lockin profile list                           # List all profiles
lockin profile show work                      # See exactly what a profile blocks
lockin profile delete old-profile
```

### Sessions

```bash
sudo lockin start work --duration 2h         # Start a focus session
sudo lockin start coding --duration 30m      # Short sprint
lockin status                                # Check remaining time (or just `lockin`)
lockin stop                                  # Refused during active sessions (by design)
```

### Always-Blocked

Block domains permanently, outside of any session:

```bash
lockin block reddit.com
lockin unblock reddit.com
```

### Schedules

```bash
lockin schedule create mornings --profile work --days mon,tue,wed,thu,fri --start 09:00 --duration 120
lockin schedule list
lockin schedule delete mornings
```

### Other

```bash
lockin apps                                   # List detected macOS apps
sudo lockin install                           # Install watchdog daemon
sudo lockin uninstall                         # Uninstall daemon (only when no active session)
lockin --version
```

## How It Works

1. **Website blocking**: Writes blocked domains to `/etc/hosts` pointing to `0.0.0.0`, then sets the system immutable flag (`chflags schg`) to prevent edits
2. **App blocking**: Kills blocked apps via `osascript` (graceful quit) then `killall` (force kill)
3. **Watchdog daemon**: A launchd daemon (`KeepAlive: true`) runs every 3 seconds to re-apply blocks if tampered with, re-kill blocked apps, and clean up when the session expires
4. **Session signing**: Sessions are signed with HMAC-SHA256 (key derived from hardware UUID). Modifying the session file invalidates the signature

## Tamper Protection

The whole point of Lockin is that you **cannot** bypass it during a session:

| Attack | Mitigation |
|--------|------------|
| Edit `/etc/hosts` | Immutable flag (`schg`) blocks writes; watchdog re-applies if removed |
| Kill the watchdog | launchd auto-respawns it immediately |
| `sudo lockin stop --force` | No code path exists to stop active sessions |
| Delete the session file | Blocks become **permanent** (no valid session = no cleanup) |
| Change the end time in session file | HMAC validation fails, watchdog ignores it |
| Reboot | Session persists at `/var/lockin/`, daemon has `RunAtLoad: true` |
| Change system clock | Watchdog cross-checks elapsed time vs 2x duration |

## Configuration

Profiles and schedules are stored in `~/.config/lockin/config.json`. Sessions are stored in `/var/lockin/session.json`.

## License

MIT
