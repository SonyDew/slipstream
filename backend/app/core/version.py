"""Single source of truth for the application version."""

from __future__ import annotations

import os

VERSION = "0.1.0"
APP_CODENAME = "Slipstream"


def build_info() -> dict[str, str]:
    """Safe, non-secret build metadata for /api/health and the about page."""
    return {
        "version": VERSION,
        "name": APP_CODENAME,
        # Populated by CI (docker build --build-arg / env) — never required.
        "commit": os.getenv("GIT_COMMIT", "unknown")[:12],
        "built_at": os.getenv("BUILD_TIMESTAMP", "unknown"),
    }
