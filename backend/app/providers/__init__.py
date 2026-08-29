"""Media providers: URL recognition plus normalisation, one family per module.

This module deliberately does **not** import the registry. Concrete providers
import from ``app.services.slideshow``, which in turn imports
``app.providers.models`` — so pulling the registry in here would make
``import app.services.slideshow`` (or any provider submodule imported first) fail
with a partially-initialised module. Import the registry directly instead:

    from app.providers.registry import registry
"""

from app.providers.base import MediaProvider, YtDlpProvider, classify_extractor_error
from app.providers.models import (
    AudioOption,
    MediaFormat,
    MediaImage,
    NormalizedMedia,
    VideoOption,
)

__all__ = [
    "AudioOption",
    "MediaFormat",
    "MediaImage",
    "MediaProvider",
    "NormalizedMedia",
    "VideoOption",
    "YtDlpProvider",
    "classify_extractor_error",
]
