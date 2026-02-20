"""/etc/hosts manipulation, DNS cache flushing, chflags protection, and pfctl firewall rules."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

HOSTS_FILE = Path("/etc/hosts")
BLOCK_START = "# >>> LOCKIN BLOCK START >>>"
BLOCK_END = "# <<< LOCKIN BLOCK END <<<"

# pfctl (packet filter) paths
PFCTL_DIR = Path("/var/lockin")
PFCTL_RULES_FILE = PFCTL_DIR / "pf_rules.conf"
PFCTL_TOKEN_FILE = PFCTL_DIR / "pfctl_token"
PFCTL_ANCHOR = "com.lockin"


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


def resolve_domain_ips(domains: list[str]) -> set[str]:
    """Resolve a list of domains to their IP addresses using socket.getaddrinfo()."""
    ips: set[str] = set()
    for domain in domains:
        if not domain:
            continue
        try:
            results = socket.getaddrinfo(domain, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _type, _proto, _canon, sockaddr in results:
                ips.add(sockaddr[0])
        except (socket.gaierror, OSError):
            continue
    # Remove loopback/localhost IPs to avoid blocking ourselves
    ips.discard("0.0.0.0")
    ips.discard("127.0.0.1")
    ips.discard("::1")
    return ips


def apply_pfctl_rules(domains: list[str]) -> bool:
    """Write pfctl rules to block IPs of given domains at the kernel packet-filter level.

    Uses a named anchor so rules can be flushed independently.
    Returns True if rules were applied successfully.
    """
    ips = resolve_domain_ips(domains)
    if not ips:
        return True  # nothing to block at IP level

    PFCTL_DIR.mkdir(parents=True, exist_ok=True)

    ip_list = " ".join(sorted(ips))
    rules = (
        f"table <lockin_blocked> persist {{ {ip_list} }}\n"
        f"block drop out quick proto {{ tcp, udp }} to <lockin_blocked>\n"
    )
    PFCTL_RULES_FILE.write_text(rules)

    # Load rules into the anchor
    result = _run(["pfctl", "-a", PFCTL_ANCHOR, "-f", str(PFCTL_RULES_FILE)])
    if result.returncode != 0:
        return False

    # Enable pfctl if not already enabled (save the token for clean disable)
    result = _run(["pfctl", "-E"])
    # pfctl -E prints "Token : <N>" on stderr
    for line in result.stderr.splitlines():
        if "Token" in line:
            token = line.split(":")[-1].strip()
            PFCTL_TOKEN_FILE.write_text(token)
            break

    return True


def remove_pfctl_rules() -> bool:
    """Flush the lockin pfctl anchor and release the enable token."""
    # Flush the anchor rules
    _run(["pfctl", "-a", PFCTL_ANCHOR, "-F", "all"])

    # Release the enable token
    if PFCTL_TOKEN_FILE.exists():
        try:
            token = PFCTL_TOKEN_FILE.read_text().strip()
            if token:
                _run(["pfctl", "-X", token])
            PFCTL_TOKEN_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    # Clean up rules file
    try:
        PFCTL_RULES_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    return True


def are_pfctl_rules_applied() -> bool:
    """Check if the lockin pfctl anchor has active rules."""
    result = _run(["pfctl", "-a", PFCTL_ANCHOR, "-sr"])
    return "lockin_blocked" in result.stdout


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

    # Also apply pfctl rules for kernel-level blocking
    apply_pfctl_rules(domains)

    return True


def remove_blocks() -> bool:
    """Remove all lockin blocks from /etc/hosts and pfctl rules.

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

    # Also remove pfctl rules
    remove_pfctl_rules()

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
