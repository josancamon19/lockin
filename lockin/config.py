"""Profile, schedule, and always-blocked persistence (~/.config/lockin/)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lockin.presets import PRESETS

CONFIG_DIR = Path.home() / ".config" / "lockin"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Profile:
    name: str
    presets: list[str] = field(default_factory=list)
    custom_sites: list[str] = field(default_factory=list)
    blocked_apps: list[str] = field(default_factory=list)

    def resolve_domains(self) -> list[str]:
        """Expand presets + custom sites into full domain list."""
        domains: list[str] = []
        for preset_name in self.presets:
            preset = PRESETS.get(preset_name)
            if preset:
                domains.extend(preset.expand_domains())
        # Expand custom sites with subdomain prefixes too
        from lockin.presets import SUBDOMAIN_PREFIXES

        for site in self.custom_sites:
            for prefix in SUBDOMAIN_PREFIXES:
                domains.append(f"{prefix}{site}")
        return list(dict.fromkeys(domains))  # dedupe, preserve order

    def resolve_apps(self) -> list[str]:
        """Collect apps from presets + explicit blocked_apps."""
        apps: list[str] = []
        for preset_name in self.presets:
            preset = PRESETS.get(preset_name)
            if preset:
                apps.extend(preset.apps)
        apps.extend(self.blocked_apps)
        return list(dict.fromkeys(apps))


@dataclass
class Schedule:
    name: str
    profile: str
    days: list[str] = field(default_factory=list)
    start_time: str = "09:00"
    duration_minutes: int = 120


@dataclass
class AlwaysBlocked:
    sites: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)


@dataclass
class Config:
    profiles: dict[str, Profile] = field(default_factory=dict)
    schedules: dict[str, Schedule] = field(default_factory=dict)
    always_blocked: AlwaysBlocked = field(default_factory=AlwaysBlocked)


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    _ensure_config_dir()
    if not CONFIG_FILE.exists():
        return Config()
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return Config()

    profiles = {}
    for name, data in raw.get("profiles", {}).items():
        profiles[name] = Profile(**data)

    schedules = {}
    for name, data in raw.get("schedules", {}).items():
        schedules[name] = Schedule(**data)

    ab = raw.get("always_blocked", {})
    always_blocked = AlwaysBlocked(
        sites=ab.get("sites", []),
        apps=ab.get("apps", []),
    )

    return Config(profiles=profiles, schedules=schedules, always_blocked=always_blocked)


def save_config(config: Config) -> None:
    _ensure_config_dir()
    data = {
        "profiles": {name: asdict(p) for name, p in config.profiles.items()},
        "schedules": {name: asdict(s) for name, s in config.schedules.items()},
        "always_blocked": asdict(config.always_blocked),
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")
