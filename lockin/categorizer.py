"""Classify activity as productive / neutral / distracting."""

from __future__ import annotations

from lockin.presets import PRESETS

# Build reverse lookups from PRESETS — all preset domains/apps are "distracting"
_DISTRACTING_DOMAINS: dict[str, str] = {}  # domain -> preset name
_DISTRACTING_APPS: dict[str, str] = {}  # app name (lower) -> preset name

for _preset_name, _preset in PRESETS.items():
    for _domain in _preset.domains:
        _DISTRACTING_DOMAINS[_domain.lower()] = _preset_name
    for _app in _preset.apps:
        _DISTRACTING_APPS[_app.lower()] = _preset_name

# Known productive apps (case-insensitive matching)
_PRODUCTIVE_APPS: set[str] = {
    "terminal",
    "iterm2",
    "iterm",
    "warp",
    "alacritty",
    "kitty",
    "hyper",
    "visual studio code",
    "code",
    "cursor",
    "xcode",
    "android studio",
    "intellij idea",
    "pycharm",
    "webstorm",
    "goland",
    "rustrover",
    "datagrip",
    "clion",
    "rider",
    "fleet",
    "nova",
    "bbedit",
    "sublime text",
    "neovim",
    "vim",
    "emacs",
    "figma",
    "sketch",
    "affinity designer",
    "affinity photo",
    "adobe photoshop",
    "adobe illustrator",
    "adobe xd",
    "blender",
    "notion",
    "obsidian",
    "linear",
    "jira",
    "asana",
    "clickup",
    "todoist",
    "things",
    "bear",
    "ulysses",
    "ia writer",
    "marked",
    "tableplus",
    "postico",
    "sequel pro",
    "dbeaver",
    "docker desktop",
    "postman",
    "insomnia",
    "charles",
    "proxyman",
    "tower",
    "fork",
    "sourcetree",
    "github desktop",
    "gitkraken",
    "finder",
    "preview",
    "calculator",
    "activity monitor",
    "system preferences",
    "system settings",
    "keynote",
    "pages",
    "numbers",
    "microsoft word",
    "microsoft excel",
    "microsoft powerpoint",
    "google docs",
    "google sheets",
    "google slides",
    "zoom",
    "around",
    "tuple",
    "loom",
}

# Known productive domains
_PRODUCTIVE_DOMAINS: set[str] = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "stackoverflow.com",
    "stackexchange.com",
    "docs.python.org",
    "developer.apple.com",
    "developer.mozilla.org",
    "learn.microsoft.com",
    "cloud.google.com",
    "console.aws.amazon.com",
    "vercel.com",
    "netlify.com",
    "render.com",
    "railway.app",
    "figma.com",
    "notion.so",
    "linear.app",
    "docs.google.com",
    "sheets.google.com",
    "slides.google.com",
    "drive.google.com",
    "overleaf.com",
    "arxiv.org",
    "chatgpt.com",
    "claude.ai",
    "gemini.google.com",
}


def categorize(
    app_name: str | None,
    domain: str | None,
    bundle_id: str | None,
) -> tuple[str, str | None]:
    """Categorize an activity.

    Returns (category, preset_match) where category is one of
    "productive", "neutral", "distracting" and preset_match is the
    preset name if the item matched a distracting preset.
    """
    app_lower = (app_name or "").lower()
    domain_lower = (domain or "").lower()

    # Check domain against distracting presets first
    if domain_lower and domain_lower in _DISTRACTING_DOMAINS:
        return "distracting", _DISTRACTING_DOMAINS[domain_lower]

    # Check app against distracting presets
    if app_lower and app_lower in _DISTRACTING_APPS:
        return "distracting", _DISTRACTING_APPS[app_lower]

    # Check domain against productive list
    if domain_lower and domain_lower in _PRODUCTIVE_DOMAINS:
        return "productive", None

    # Check app against productive list
    if app_lower and app_lower in _PRODUCTIVE_APPS:
        return "productive", None

    return "neutral", None
