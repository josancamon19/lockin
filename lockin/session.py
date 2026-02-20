"""Session state management with HMAC signing for tamper detection."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SESSION_DIR = Path("/var/lockin")
SESSION_FILE = SESSION_DIR / "session.json"
HMAC_ITERATIONS = 100_000


def _get_hardware_uuid() -> str:
    """Get the macOS hardware UUID for key derivation."""
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return "fallback-uuid-lockin-key"


def _derive_key() -> bytes:
    """Derive HMAC key from hardware UUID using PBKDF2."""
    uuid = _get_hardware_uuid()
    return hashlib.pbkdf2_hmac(
        "sha256",
        uuid.encode(),
        b"lockin-session-salt",
        HMAC_ITERATIONS,
    )


def _compute_hmac(data: dict) -> str:
    """Compute HMAC-SHA256 signature over session data (excluding signature field)."""
    signing_data = {k: v for k, v in sorted(data.items()) if k != "hmac_signature"}
    payload = json.dumps(signing_data, sort_keys=True).encode()
    key = _derive_key()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


@dataclass
class Session:
    profile_name: str
    start_time: float
    end_time: float
    duration_seconds: int
    blocked_domains: list[str] = field(default_factory=list)
    blocked_apps: list[str] = field(default_factory=list)
    hmac_signature: str = ""

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.end_time

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.end_time - time.time())

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "blocked_domains": self.blocked_domains,
            "blocked_apps": self.blocked_apps,
            "hmac_signature": self.hmac_signature,
        }

    def sign(self) -> None:
        """Compute and set the HMAC signature."""
        data = self.to_dict()
        self.hmac_signature = _compute_hmac(data)

    def verify(self) -> bool:
        """Verify the HMAC signature is valid."""
        data = self.to_dict()
        expected = _compute_hmac(data)
        return hmac.compare_digest(self.hmac_signature, expected)

    def is_clock_tampered(self) -> bool:
        """Detect if system clock was set backwards to fake expiry.

        If elapsed wall-clock time exceeds 2x the original duration, something is wrong.
        Also reject if current time is before the start time.
        """
        now = time.time()
        if now < self.start_time:
            return True
        if self.elapsed_seconds > self.duration_seconds * 2:
            return True
        return False


def create_session(
    profile_name: str,
    duration_seconds: int,
    blocked_domains: list[str],
    blocked_apps: list[str],
) -> Session:
    """Create, sign, and save a new session."""
    now = time.time()
    session = Session(
        profile_name=profile_name,
        start_time=now,
        end_time=now + duration_seconds,
        duration_seconds=duration_seconds,
        blocked_domains=blocked_domains,
        blocked_apps=blocked_apps,
    )
    session.sign()
    save_session(session)
    return session


def set_session_immutable() -> bool:
    """Set the system immutable flag on the session file."""
    if not SESSION_FILE.exists():
        return False
    result = subprocess.run(
        ["chflags", "schg", str(SESSION_FILE)], capture_output=True
    )
    return result.returncode == 0


def remove_session_immutable() -> bool:
    """Remove the system immutable flag from the session file."""
    if not SESSION_FILE.exists():
        return True
    result = subprocess.run(
        ["chflags", "noschg", str(SESSION_FILE)], capture_output=True
    )
    return result.returncode == 0


def is_session_immutable() -> bool:
    """Check if the session file has the system immutable flag set."""
    if not SESSION_FILE.exists():
        return False
    result = subprocess.run(
        ["ls", "-lO", str(SESSION_FILE)], capture_output=True, text=True
    )
    return "schg" in result.stdout


def save_session(session: Session) -> None:
    """Write session to disk and protect with immutable flag."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    remove_session_immutable()
    SESSION_FILE.write_text(json.dumps(session.to_dict(), indent=2) + "\n")
    set_session_immutable()


def load_session() -> Session | None:
    """Load session from disk. Returns None if missing or unparseable."""
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        return Session(**data)
    except (json.JSONDecodeError, TypeError, KeyError, OSError):
        return None


def delete_session() -> None:
    """Remove the session file (removing immutable flag first)."""
    try:
        remove_session_immutable()
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def get_active_session() -> Session | None:
    """Load and validate the active session. Returns None if no valid active session."""
    session = load_session()
    if session is None:
        return None
    if not session.verify():
        return None  # tampered
    if session.is_expired:
        return None
    return session
