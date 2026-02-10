"""Core activity tracking — frontmost app, window title, URL extraction."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from lockin.activity_db import close_activity, init_db, insert_activity
from lockin.categorizer import categorize

# -- macOS framework imports (lazy, so module can be imported on any platform) --

_NS_WORKSPACE = None
_CG = None
_AX = None
_HIServices = None


def _ensure_imports() -> None:
    global _NS_WORKSPACE, _CG, _AX, _HIServices
    if _NS_WORKSPACE is not None:
        return
    try:
        from AppKit import NSWorkspace
        _NS_WORKSPACE = NSWorkspace.sharedWorkspace()
    except ImportError:
        pass
    try:
        import Quartz
        _CG = Quartz
    except ImportError:
        pass
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXErrorSuccess,
        )
        _AX = type("AX", (), {
            "AXIsProcessTrustedWithOptions": staticmethod(AXIsProcessTrustedWithOptions),
            "AXUIElementCopyAttributeValue": staticmethod(AXUIElementCopyAttributeValue),
            "AXUIElementCreateApplication": staticmethod(AXUIElementCreateApplication),
            "kAXErrorSuccess": kAXErrorSuccess,
        })
    except ImportError:
        pass
    try:
        from HIServices import kAXTrustedCheckOptionPrompt
        _HIServices = type("HI", (), {
            "kAXTrustedCheckOptionPrompt": kAXTrustedCheckOptionPrompt,
        })
    except ImportError:
        pass


# -- Known browser bundle IDs --

_BROWSER_BUNDLE_IDS: set[str] = {
    "com.apple.safari",
    "com.google.chrome",
    "org.mozilla.firefox",
    "com.microsoft.edgemac",
    "com.brave.browser",
    "com.operasoftware.opera",
    "com.vivaldi.vivaldi",
    "company.thebrowser.browser",  # Arc
    "org.chromium.chromium",
    "com.sigmaos.sigmaos",
    "com.nickvision.nightowl",
}

_BROWSER_NAME_PATTERNS: set[str] = {
    "safari",
    "chrome",
    "firefox",
    "edge",
    "brave",
    "opera",
    "vivaldi",
    "arc",
    "atlas",
    "orion",
    "chromium",
    "sigmaos",
    "zen",
    "waterfox",
    "tor browser",
    "duckduckgo",
}

# Apps to ignore (screen locked / screensaver)
_IGNORE_APPS: set[str] = {
    "loginwindow",
    "screensaverengine",
    "lock screen",
}

# URL regex for matching URL-like strings
_URL_RE = re.compile(r"^https?://\S+", re.IGNORECASE)
_DOMAIN_LIKE_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+(/\S*)?$")


def get_frontmost_app() -> tuple[str | None, str | None, int | None]:
    """Return (app_name, bundle_id, pid) for the frontmost application."""
    _ensure_imports()
    if _NS_WORKSPACE is None:
        return None, None, None
    try:
        app = _NS_WORKSPACE.frontmostApplication()
        if app is None:
            return None, None, None
        name = app.localizedName()
        bundle = app.bundleIdentifier()
        pid = app.processIdentifier()
        return name, bundle, pid
    except Exception:
        return None, None, None


def get_window_title(pid: int) -> str | None:
    """Get the window title for a given PID using CGWindowListCopyWindowInfo."""
    _ensure_imports()
    if _CG is None:
        return None
    try:
        window_list = _CG.CGWindowListCopyWindowInfo(
            _CG.kCGWindowListOptionOnScreenOnly | _CG.kCGWindowListExcludeDesktopElements,
            _CG.kCGNullWindowID,
        )
        if window_list is None:
            return None
        for window in window_list:
            if window.get("kCGWindowOwnerPID") == pid:
                title = window.get("kCGWindowName")
                if title:
                    return str(title)
        return None
    except Exception:
        return None


def is_browser(bundle_id: str | None, app_name: str | None) -> bool:
    """Check if the given app is a web browser."""
    if bundle_id and bundle_id.lower() in _BROWSER_BUNDLE_IDS:
        return True
    if app_name:
        name_lower = app_name.lower()
        for pattern in _BROWSER_NAME_PATTERNS:
            if pattern in name_lower:
                return True
    return False


def _looks_like_url(value: str) -> bool:
    """Check if a string looks like a URL."""
    if _URL_RE.match(value):
        return True
    if _DOMAIN_LIKE_RE.match(value):
        return True
    return False


def _extract_domain(url: str) -> str | None:
    """Extract domain from a URL string."""
    if not url:
        return None
    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host:
            # Strip www. prefix for cleaner domain
            if host.startswith("www."):
                host = host[4:]
            return host.lower()
    except Exception:
        pass
    return None


# Cache for URL extraction to avoid re-traversal
_url_cache: dict[tuple[int, str | None], str | None] = {}
_url_cache_max = 50


def extract_browser_url(pid: int, window_title: str | None = None) -> str | None:
    """Extract the URL from a browser's address bar via the Accessibility API.

    Uses AXUIElement traversal to find text fields that contain URL-like values.
    Results are cached by (pid, window_title) to avoid repeated traversal.
    """
    _ensure_imports()
    if _AX is None:
        return None

    cache_key = (pid, window_title)
    if cache_key in _url_cache:
        return _url_cache[cache_key]

    try:
        app_element = _AX.AXUIElementCreateApplication(pid)
        url = _walk_ax_tree(app_element, max_depth=10)

        # Manage cache size
        if len(_url_cache) >= _url_cache_max:
            _url_cache.clear()
        _url_cache[cache_key] = url
        return url
    except Exception:
        return None


def _ax_get_attr(element: object, attr: str) -> object | None:
    """Get an AX attribute value, returning None on failure."""
    try:
        err, value = _AX.AXUIElementCopyAttributeValue(element, attr, None)
        if err == _AX.kAXErrorSuccess:
            return value
    except Exception:
        pass
    return None


def _walk_ax_tree(element: object, max_depth: int, depth: int = 0) -> str | None:
    """Recursively walk AX tree looking for URL-like text values."""
    if depth >= max_depth:
        return None

    role = _ax_get_attr(element, "AXRole")
    role_str = str(role) if role else ""

    # Check text fields, combo boxes, and static text for URL-like values
    if role_str in ("AXTextField", "AXComboBox", "AXStaticText", "AXTextArea"):
        value = _ax_get_attr(element, "AXValue")
        if value and isinstance(value, str) and _looks_like_url(value):
            return value

    # Also check AXValue on groups that might contain the URL bar
    if role_str in ("AXGroup", "AXToolbar"):
        value = _ax_get_attr(element, "AXValue")
        if value and isinstance(value, str) and _looks_like_url(value):
            return value

    # Recurse into children
    children = _ax_get_attr(element, "AXChildren")
    if children:
        try:
            for child in children:
                result = _walk_ax_tree(child, max_depth, depth + 1)
                if result:
                    return result
        except Exception:
            pass

    return None


def request_accessibility_permission() -> bool:
    """Prompt the user for Accessibility permission. Returns current trust status."""
    _ensure_imports()
    if _AX is None or _HIServices is None:
        return False
    try:
        options = {_HIServices.kAXTrustedCheckOptionPrompt: True}
        return _AX.AXIsProcessTrustedWithOptions(options)
    except Exception:
        return False


class ActivityTracker:
    """Tracks frontmost app activity, writing to SQLite on state changes."""

    def __init__(self) -> None:
        init_db()
        self._current_row_id: int | None = None
        self._current_app: str | None = None
        self._current_domain: str | None = None
        self._current_bundle: str | None = None

    def poll(self) -> None:
        """Called every tick. Detects state changes and writes to DB."""
        app_name, bundle_id, pid = get_frontmost_app()

        if app_name is None:
            return

        # Ignore lock screen / screensaver
        if app_name.lower() in _IGNORE_APPS:
            self._close_current()
            return

        # Determine domain if browser
        domain: str | None = None
        url: str | None = None
        window_title: str | None = None

        if pid is not None:
            window_title = get_window_title(pid)

            if is_browser(bundle_id, app_name):
                url = extract_browser_url(pid, window_title)
                if url:
                    domain = _extract_domain(url)

        # Detect state change: different app OR different domain
        if app_name == self._current_app and domain == self._current_domain:
            return  # No change

        # Close previous activity
        self._close_current()

        # Categorize
        category, preset_match = categorize(app_name, domain, bundle_id)

        # Insert new row
        now = datetime.now().isoformat()
        self._current_row_id = insert_activity(
            started_at=now,
            app_name=app_name,
            bundle_id=bundle_id,
            window_title=window_title,
            url=url,
            domain=domain,
            category=category,
            preset_match=preset_match,
        )
        self._current_app = app_name
        self._current_domain = domain
        self._current_bundle = bundle_id

    def _close_current(self) -> None:
        """Close the current activity row with an ended_at timestamp."""
        if self._current_row_id is not None:
            now = datetime.now().isoformat()
            close_activity(self._current_row_id, now)
            self._current_row_id = None
            self._current_app = None
            self._current_domain = None
            self._current_bundle = None

    def shutdown(self) -> None:
        """Close the current activity row on app quit."""
        self._close_current()
