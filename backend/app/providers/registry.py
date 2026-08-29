"""Provider registry.

Single lookup point mapping a URL to the provider that should handle it. Adding
a platform means writing one class and appending it here — nothing else in the
application changes.
"""

from __future__ import annotations

from app.core.errors import PlatformDisabledError, UnsupportedURLError
from app.core.logging import get_logger
from app.providers.base import MediaProvider
from app.providers.douyin import DouyinProvider
from app.providers.facebook import FacebookProvider
from app.providers.generic import GenericProvider
from app.providers.instagram import InstagramProvider
from app.providers.reddit import RedditProvider
from app.providers.soundcloud import SoundCloudProvider
from app.providers.tiktok import TikTokProvider
from app.providers.twitter import TwitterProvider
from app.providers.vimeo import VimeoProvider
from app.providers.youtube import YouTubeProvider

log = get_logger("slipstream.registry")


class ProviderRegistry:
    def __init__(self, providers: list[MediaProvider] | None = None) -> None:
        self._providers: list[MediaProvider] = []
        self._fallback: MediaProvider | None = None
        for provider in providers if providers is not None else _default_providers():
            self.register(provider)

    def register(self, provider: MediaProvider) -> None:
        if provider.platform == "generic":
            self._fallback = provider
            return
        self._providers.append(provider)
        # Highest priority first, so ordering is independent of registration.
        self._providers.sort(key=lambda p: -p.priority)

    # -- lookup ----------------------------------------------------------- #
    def find(self, url: str) -> MediaProvider:
        """Return the provider for ``url``, falling back to generic."""
        for provider in self._providers:
            try:
                if provider.matches(url):
                    return provider
            except Exception as exc:
                log.warning(
                    "provider match raised", provider=provider.platform, error=type(exc).__name__
                )
        if self._fallback is None:  # pragma: no cover - always registered
            raise UnsupportedURLError()
        return self._fallback

    def find_enabled(self, url: str, allowed: list[str] | None = None) -> MediaProvider:
        """Like :meth:`find`, but enforces the admin platform allow-list."""
        provider = self.find(url)
        if allowed and provider.platform not in allowed:
            raise PlatformDisabledError(f"Downloads from {provider.label} are currently disabled.")
        return provider

    def detect_platform(self, url: str) -> str:
        return self.find(url).platform

    def get(self, platform: str) -> MediaProvider | None:
        if platform == "generic":
            return self._fallback
        for provider in self._providers:
            if provider.platform == platform:
                return provider
        return None

    # -- introspection ---------------------------------------------------- #
    @property
    def providers(self) -> list[MediaProvider]:
        out = list(self._providers)
        if self._fallback:
            out.append(self._fallback)
        return out

    def platform_names(self) -> list[str]:
        return [p.platform for p in self.providers]

    def describe(self) -> list[dict[str, object]]:
        """Payload for the frontend platform list and admin allow-list UI."""
        return [
            {
                "platform": p.platform,
                "label": p.label,
                "domains": list(p.domains),
                "is_fallback": p.platform == "generic",
                "operational": p.operational,
            }
            for p in self.providers
        ]


def _default_providers() -> list[MediaProvider]:
    return [
        YouTubeProvider(),
        TikTokProvider(),
        DouyinProvider(),
        InstagramProvider(),
        TwitterProvider(),
        FacebookProvider(),
        RedditProvider(),
        VimeoProvider(),
        SoundCloudProvider(),
        GenericProvider(),
    ]


registry = ProviderRegistry()
