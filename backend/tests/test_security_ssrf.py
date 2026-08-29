"""SSRF protection tests.

These are the security-critical cases from the threat model: every one of them
must be rejected before the extractor ever sees the URL.
"""

from __future__ import annotations

import pytest

from app.core.errors import BlockedTargetError, InvalidURLError
from app.core.ssrf import (
    assert_url_allowed,
    is_public_address,
    is_url_allowed,
    normalize_url,
    safe_redirect_target,
)

# Cases named explicitly in the requirements, plus obfuscated equivalents.
BLOCKED_URLS = [
    "http://127.0.0.1",
    "http://127.0.0.1:8000/admin",
    "https://127.0.0.1/",
    "http://127.1/",
    "http://localhost",
    "http://localhost:8000/api/health",
    "http://LOCALHOST/",
    "http://localhost.localdomain/",
    "http://169.254.169.254",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://169.254.170.2/v2/credentials",
    "http://100.100.100.200/latest/meta-data/",
    "http://192.0.0.192/opc/v1/instance/",
    "http://10.0.0.1",
    "http://10.255.255.254/",
    "http://192.168.1.1",
    "http://192.168.0.100:8080/",
    "http://172.16.0.1",
    "http://172.31.255.255/",
    "http://[::1]/",
    "http://[::1]:80/",
    "http://[::ffff:127.0.0.1]/",
    "http://[fd00::1]/",
    "http://[fe80::1]/",
    "http://[fc00::1234]/",
    "http://0.0.0.0/",
    "http://0/",
    # Obfuscated loopback encodings.
    "http://2130706433/",
    "http://0x7f000001/",
    "http://0177.0.0.1/",
    "http://0xa000001/",
    # Internal DNS names.
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://metadata/",
    "http://instance-data/",
    "http://intranet-host/",
    "http://db.internal/",
    "http://printer.local/",
    "http://server.lan/",
    "http://box.home.arpa/",
    # CGNAT and reserved space.
    "http://100.64.0.1/",
    "http://198.18.0.1/",
    "http://224.0.0.1/",
    "http://240.0.0.1/",
    # Credentials in the authority confuse naive host parsers.
    "http://user:pass@example.com/",
    "https://admin:secret@127.0.0.1/",
]

MALFORMED_URLS = [
    "",
    "   ",
    "not a url",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "http://",
    "https://",
    "http://exa mple.com/",
    "http://example.com:99999/",
    "http://exam\nple.com/",
    "http://example.com/\r\nHost: evil",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_blocked_targets_are_rejected(url: str) -> None:
    with pytest.raises((BlockedTargetError, InvalidURLError)):
        assert_url_allowed(url)
    assert is_url_allowed(url) is False


@pytest.mark.parametrize("url", MALFORMED_URLS)
def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises((InvalidURLError, BlockedTargetError)):
        assert_url_allowed(url)


def test_non_http_schemes_are_rejected() -> None:
    for scheme in ("ftp", "gopher", "dict", "sftp", "ldap"):
        with pytest.raises((BlockedTargetError, InvalidURLError)):
            assert_url_allowed(f"{scheme}://example.com/resource")


def test_public_hostname_is_allowed_without_dns() -> None:
    """Hostname syntax and policy pass; DNS is skipped so the test is offline."""
    result = assert_url_allowed("https://www.youtube.com/watch?v=abc123", resolve_dns=False)
    assert result.hostname == "www.youtube.com"
    assert result.scheme == "https"
    assert result.port == 443


def test_query_string_is_preserved_and_fragment_dropped() -> None:
    result = assert_url_allowed("https://www.youtube.com/watch?v=abc&t=30#frag", resolve_dns=False)
    assert result.url == "https://www.youtube.com/watch?v=abc&t=30"


def test_scheme_is_added_when_missing() -> None:
    assert normalize_url("youtu.be/abc123") == "https://youtu.be/abc123"
    assert normalize_url("//youtu.be/abc") == "https://youtu.be/abc"


def test_redirect_to_private_address_is_rejected() -> None:
    """A public URL redirecting inward must not be followed."""
    for target in ("http://127.0.0.1/", "/", "http://169.254.169.254/"):
        if target == "/":
            # A relative redirect resolves against the public base, so it is fine.
            assert safe_redirect_target(
                target, base_url="https://www.youtube.com/watch"
            ).startswith("https://www.youtube.com/")
            continue
        with pytest.raises(BlockedTargetError):
            safe_redirect_target(target, base_url="https://www.youtube.com/watch")


def test_is_public_address() -> None:
    assert is_public_address("8.8.8.8") is True
    assert is_public_address("1.1.1.1") is True
    assert is_public_address("2606:4700:4700::1111") is True

    for private in (
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "fe80::1",
        "0.0.0.0",
        "224.0.0.1",
        "not-an-ip",
    ):
        assert is_public_address(private) is False, private


def test_url_length_is_bounded() -> None:
    with pytest.raises(InvalidURLError):
        assert_url_allowed("https://example.com/" + "a" * 3000)


def test_dns_resolution_failure_is_blocked_not_crashed() -> None:
    with pytest.raises(BlockedTargetError):
        assert_url_allowed("https://this-domain-should-not-resolve-slipstream-test.invalid/")


def test_extractor_refuses_blocked_url_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The extractor entry point must validate before touching yt-dlp."""
    import asyncio

    from app.services import extractor

    called = False

    def _boom(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("yt-dlp must not be reached for a blocked URL")

    monkeypatch.setattr(extractor, "_run_sync_extract", _boom)

    with pytest.raises(BlockedTargetError):
        asyncio.run(extractor.extract_info("http://169.254.169.254/latest/meta-data/"))
    assert called is False
