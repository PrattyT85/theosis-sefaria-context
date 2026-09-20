"""Shared configuration for the Sefaria Context service."""
from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "postgresql://sefaria_context@/sefaria_context?host=/var/run/postgresql"


def database_url(value: str | None = None) -> str:
    return value or os.environ.get("SEFARIA_CONTEXT_DATABASE_URL", DEFAULT_DATABASE_URL)
