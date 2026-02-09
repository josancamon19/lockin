"""/etc/hosts manipulation, DNS cache flushing, and chflags protection."""

from __future__ import annotations

import subprocess
from pathlib import Path

HOSTS_FILE = Path("/etc/hosts")
BLOCK_START = "# >>> LOCKIN BLOCK START >>>"
BLOCK_END = "# <<< LOCKIN BLOCK END <<<"


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _read_hosts() -> str:
    return HOSTS_FILE.read_text()


def _get_block_entries(domains: list[str]) -> str:
    """Generate /etc/hosts block entries."""
    lines = [BLOCK_START]
    for domain in sorted(set(domains)):
        if domain:  # skip empty strings
            lines.append(f"0.0.0.0 {domain}")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def _strip_existing_blocks(content: str) -> str:
    """Remove any existing lockin block section from hosts content."""
    lines = content.splitlines()
    result: list[str] = []
    inside_block = False
    for line in lines:
        if line.strip() == BLOCK_START:
            inside_block = True
            continue
        if line.strip() == BLOCK_END:
            inside_block = False
            continue
        if not inside_block:
            result.append(line)
    # Remove trailing blank lines from our section
    while result and result[-1].strip() == "":
        result.pop()
    return "\n".join(result)


def remove_immutable_flag() -> bool:
    """Remove the system immutable flag from /etc/hosts."""
    result = _run(["chflags", "noschg", str(HOSTS_FILE)])
    return result.returncode == 0


def set_immutable_flag() -> bool:
    """Set the system immutable flag on /etc/hosts to prevent edits."""
    result = _run(["chflags", "schg", str(HOSTS_FILE)])
    return result.returncode == 0


def flush_dns_cache() -> None:
    """Flush the macOS DNS cache."""
    _run(["dscacheutil", "-flushcache"])
    _run(["killall", "-HUP", "mDNSResponder"])


def apply_blocks(domains: list[str]) -> bool:
    """Write domain blocks to /etc/hosts and protect the file.

    Returns True if blocks were applied successfully.
    """
    if not domains:
        return True

    remove_immutable_flag()

    try:
        current = _read_hosts()
        clean = _strip_existing_blocks(current)
        block_entries = _get_block_entries(domains)
        new_content = clean + "\n\n" + block_entries + "\n"
        HOSTS_FILE.write_text(new_content)
    except PermissionError:
        return False

    set_immutable_flag()
    flush_dns_cache()
    return True


def remove_blocks() -> bool:
    """Remove all lockin blocks from /etc/hosts.

    Returns True if blocks were removed successfully.
    """
    remove_immutable_flag()

    try:
        current = _read_hosts()
        clean = _strip_existing_blocks(current)
        # Ensure file ends with a newline
        if not clean.endswith("\n"):
            clean += "\n"
        HOSTS_FILE.write_text(clean)
    except PermissionError:
        return False

    flush_dns_cache()
    return True


def are_blocks_applied(domains: list[str]) -> bool:
    """Check if the expected blocks are present in /etc/hosts."""
    if not domains:
        return True
    try:
        content = _read_hosts()
    except PermissionError:
        return False
    return BLOCK_START in content and BLOCK_END in content


def is_immutable() -> bool:
    """Check if /etc/hosts has the system immutable flag set."""
    result = _run(["ls", "-lO", str(HOSTS_FILE)])
    return "schg" in result.stdout
