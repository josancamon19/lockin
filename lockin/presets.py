"""Built-in website and app category presets."""

from __future__ import annotations

from dataclasses import dataclass, field


SUBDOMAIN_PREFIXES = ["", "www.", "m.", "api.", "mobile.", "app."]


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    domains: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)

    def expand_domains(self) -> list[str]:
        """Expand each domain into subdomain variants."""
        expanded: list[str] = []
        for domain in self.domains:
            for prefix in SUBDOMAIN_PREFIXES:
                expanded.append(f"{prefix}{domain}")
        return expanded


PRESETS: dict[str, Preset] = {
    "social": Preset(
        name="social",
        description="Social media platforms",
        domains=[
            "x.com",
            "twitter.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "reddit.com",
            "threads.net",
            "snapchat.com",
            "linkedin.com",
        ],
        apps=["Discord"],
    ),
    "entertainment": Preset(
        name="entertainment",
        description="Streaming and entertainment",
        domains=[
            "youtube.com",
            "netflix.com",
            "twitch.tv",
            "hulu.com",
            "disneyplus.com",
            "primevideo.com",
            "spotify.com",
        ],
        apps=["Spotify"],
    ),
    "news": Preset(
        name="news",
        description="News websites",
        domains=[
            "news.ycombinator.com",
            "cnn.com",
            "bbc.com",
            "nytimes.com",
            "theguardian.com",
        ],
        apps=[],
    ),
    "communication": Preset(
        name="communication",
        description="Messaging, email, and chat",
        domains=[
            "web.whatsapp.com",
            "whatsapp.com",
            "mail.google.com",
            "gmail.com",
            "mail.superhuman.com",
            "superhuman.com",
        ],
        apps=["WhatsApp", "Messages", "Superhuman", "Mail"],
    ),
    "gaming": Preset(
        name="gaming",
        description="Gaming platforms",
        domains=[
            "steampowered.com",
            "store.steampowered.com",
            "epicgames.com",
            "riotgames.com",
        ],
        apps=["Steam", "Epic Games Launcher"],
    ),
}


def get_preset(name: str) -> Preset | None:
    return PRESETS.get(name)


def list_presets() -> list[Preset]:
    return list(PRESETS.values())
