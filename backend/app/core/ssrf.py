"""SSRF protection.

The service accepts arbitrary user-supplied URLs and hands them to an
extractor, which makes it a textbook SSRF target. This module is the single
choke point that decides whether a URL may be fetched at all.

Defence layers:

1. Scheme allow-list (http/https only) — blocks ``file://``, ``gopher://``,
   ``dict://`` and friends.
2. Host literal checks — rejects IP literals in private/reserved ranges,
   including obfuscated forms (decimal, octal, hex, IPv4-mapped IPv6).
3. DNS resolution — every resolved A/AAAA record must be a public address.
   A hostname that resolves to *any* private address is rejected outright.
4. Redirect re-validation — callers must re-run :func:`assert_url_allowed`
   on each hop; :class:`SafeRedirectPolicy` implements that for httpx.

DNS rebinding: because a hostname can resolve differently between our check
and the extractor's fetch, we also return the validated IP set so callers can
pin the connection. yt-dlp does not expose connection pinning, so for that
path we accept a documented residual risk and rely on the outbound network
policy recommended in docs/SECURITY.md.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlsplit, urlunsplit

from app.core.config import settings
from app.core.errors import BlockedTargetError, InvalidURLError

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_URL_LENGTH = 2048

# Cloud metadata endpoints. These are link-local (already covered by the
# is_private checks) but are listed explicitly so the intent is greppable and
# so any future non-link-local metadata host is easy to add.
METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",  # AWS / GCP / Azure / Oracle / DigitalOcean IMDS
        "169.254.170.2",  # AWS ECS task metadata
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud (legacy endpoint)
        "fd00:ec2::254",  # AWS IMDSv6
        "metadata.google.internal",
        "metadata.goog",
        "metadata",
        "instance-data",
    }
)

# Hostnames that must never be resolved, regardless of what DNS says.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "broadcasthost",
    }
)

# Internal-only TLDs and suffixes (RFC 6762 / RFC 8375 / common corp usage).
BLOCKED_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".intranet",
    ".corp",
    ".home",
    ".lan",
    ".private",
    ".home.arpa",
    ".in-addr.arpa",
    ".ip6.arpa",
)

# Extra IPv4 ranges that ``ipaddress`` does not flag as private but that no
# legitimate media host uses.
_EXTRA_BLOCKED_V4 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
)

_EXTRA_BLOCKED_V6 = (
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link local
    ipaddress.ip_network("ff00::/8"),  # multicast
    ipaddress.ip_network("2001:db8::/32"),  # documentation
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 — can reach private v4
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped
)

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9_]([a-zA-Z0-9_-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.?$"
)


@dataclass
class URLCheckResult:
    """Outcome of a successful validation."""

    url: str
    scheme: str
    hostname: str
    port: int
    addresses: list[str] = field(default_factory=list)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when an address must never be contacted."""
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    if isinstance(ip, ipaddress.IPv6Address):
        # An IPv4-mapped/6to4 address can smuggle a private v4 target.
        if ip.ipv4_mapped is not None:
            return _is_blocked_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _is_blocked_ip(ip.sixtofour)
        teredo = getattr(ip, "teredo", None)
        if teredo is not None:
            server, client = teredo
            return _is_blocked_ip(server) or _is_blocked_ip(client)
        return any(ip in net for net in _EXTRA_BLOCKED_V6)

    return any(ip in net for net in _EXTRA_BLOCKED_V4)


def is_public_address(value: str) -> bool:
    """Public API used by tests and callers holding a bare address string."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not _is_blocked_ip(ip)


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a host as an IP literal, including obfuscated encodings.

    Handles the classic SSRF bypass forms: ``2130706433`` (decimal),
    ``0x7f000001`` (hex), ``0177.0.0.1`` (octal) and ``[::1]`` (bracketed v6).
    """
    candidate = host.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]

    # Strip an IPv6 zone index (fe80::1%eth0) before parsing.
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]

    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass

    # Bare integer -> IPv4 (e.g. http://2130706433/ is 127.0.0.1)
    if candidate.isdigit():
        try:
            as_int = int(candidate)
        except ValueError:
            return None
        if 0 <= as_int <= 0xFFFFFFFF:
            return ipaddress.ip_address(as_int)
        return None

    # Hex form: 0x7f000001
    lowered = candidate.lower()
    if lowered.startswith("0x"):
        try:
            as_int = int(lowered, 16)
        except ValueError:
            return None
        if 0 <= as_int <= 0xFFFFFFFF:
            return ipaddress.ip_address(as_int)
        return None

    # Dotted forms with octal/hex octets: 0177.0.0.1, 0x7f.0.0.1
    parts = candidate.split(".")
    if 2 <= len(parts) <= 4 and all(parts):
        try:
            octets = []
            for part in parts:
                low = part.lower()
                if low.startswith("0x"):
                    octets.append(int(low, 16))
                elif low.startswith("0") and len(low) > 1:
                    octets.append(int(low, 8))
                elif low.isdigit():
                    octets.append(int(low))
                else:
                    return None
            if len(octets) == 4 and all(0 <= o <= 255 for o in octets):
                return ipaddress.ip_address(".".join(str(o) for o in octets))
        except ValueError:
            return None
    return None


def _resolve(hostname: str, port: int) -> list[str]:
    """Resolve a hostname to every A/AAAA address, or raise."""
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise BlockedTargetError(
            "That address could not be resolved.",
            detail=f"DNS resolution failed for {hostname}",
        ) from exc

    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and isinstance(sockaddr[0], str):
            addresses.append(sockaddr[0])
    if not addresses:
        raise BlockedTargetError("That address could not be resolved.")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(addresses))


def normalize_url(raw: str) -> str:
    """Trim, add a scheme when missing, and strip fragments/whitespace."""
    if not raw or not isinstance(raw, str):
        raise InvalidURLError()

    candidate = raw.strip().strip("​‎‏")
    # Reject control characters outright: they enable header/CRLF injection.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in candidate):
        raise InvalidURLError("The link contains invalid characters.")

    if len(candidate) > MAX_URL_LENGTH:
        raise InvalidURLError("That link is too long.")

    if "://" not in candidate:
        # Users routinely paste `youtu.be/xyz`; assume https rather than reject.
        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        else:
            candidate = f"https://{candidate}"

    parts = urlsplit(candidate)
    if not parts.scheme or not parts.netloc:
        raise InvalidURLError()

    # Drop the fragment; it is never meaningful server-side.
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ""))


def assert_url_allowed(raw_url: str, *, resolve_dns: bool = True) -> URLCheckResult:
    """Validate a user-supplied URL or raise.

    Raises :class:`InvalidURLError` for malformed input and
    :class:`BlockedTargetError` for anything pointing at a non-public address.
    """
    url = normalize_url(raw_url)
    parts = urlparse(url)

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedTargetError(
            "Only http and https links are supported.",
            detail=f"blocked scheme: {scheme}",
        )

    # Credentials in the authority (http://user:pass@host) are a common way to
    # confuse host parsers; refuse them.
    if parts.username or parts.password:
        raise BlockedTargetError(
            "Links containing credentials are not accepted.",
            detail="url contained userinfo",
        )

    hostname = parts.hostname
    if not hostname:
        raise InvalidURLError()
    hostname = hostname.strip().rstrip(".").lower()
    if not hostname:
        raise InvalidURLError()

    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:  # out-of-range port
        raise InvalidURLError("That link has an invalid port.") from exc

    # A test-only escape hatch so the suite can exercise the happy path against
    # a local fixture server. Never enabled in production config.
    bypass = settings.ALLOW_PRIVATE_NETWORK_TARGETS and not settings.is_production

    if not bypass and (hostname in BLOCKED_HOSTNAMES or hostname in METADATA_HOSTS):
        raise BlockedTargetError(detail=f"blocked hostname: {hostname}")

    blocked_suffix = any(
        hostname == suffix.lstrip(".") or hostname.endswith(suffix) for suffix in BLOCKED_SUFFIXES
    )
    if not bypass and blocked_suffix:
        raise BlockedTargetError(detail=f"blocked suffix: {hostname}")

    # A single-label host (no dot) is an internal DNS name by definition.
    literal = _parse_ip_literal(hostname)
    if not bypass and literal is None and "." not in hostname:
        raise BlockedTargetError(detail=f"single-label hostname: {hostname}")

    if literal is not None:
        if _is_blocked_ip(literal) and not bypass:
            raise BlockedTargetError(detail=f"blocked ip literal: {literal}")
        return URLCheckResult(url, scheme, hostname, port, [str(literal)])

    if not _HOSTNAME_RE.match(hostname):
        raise InvalidURLError("That link has an invalid hostname.")

    if not resolve_dns or bypass:
        return URLCheckResult(url, scheme, hostname, port, [])

    addresses = _resolve(hostname, port)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - getaddrinfo returned nonsense
            raise BlockedTargetError(detail=f"unparseable resolved address: {address}") from None
        if _is_blocked_ip(ip):
            # Deliberately vague to the user; specifics go to the log only.
            raise BlockedTargetError(
                detail=f"{hostname} resolved to non-public address {address}",
            )

    return URLCheckResult(url, scheme, hostname, port, addresses)


def is_url_allowed(raw_url: str) -> bool:
    """Boolean convenience wrapper around :func:`assert_url_allowed`."""
    try:
        assert_url_allowed(raw_url)
    except (InvalidURLError, BlockedTargetError):
        return False
    return True


def safe_redirect_target(location: str, *, base_url: str) -> str:
    """Validate a redirect ``Location`` before following it."""
    from urllib.parse import urljoin

    absolute = urljoin(base_url, location)
    assert_url_allowed(absolute)
    return absolute
