"""Small dependency-free .env loader shared by repository scripts."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines without overriding variables already in the shell."""
    if not path.is_file():
        return
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SystemExit(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            raise SystemExit(f"{path}:{number}: invalid environment variable name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


# Values long enough to redact. Shorter strings would punch holes in ordinary log text.
_SECRET_ENV = (
    "COS_SECRET_ID",
    "COS_SECRET_KEY",
    "COS_SESSION_TOKEN",
    "COS_BUCKET",
    "COS_ENDPOINT",
    "CDN_SECRET_ID",
    "CDN_SECRET_KEY",
    "CDN_SESSION_TOKEN",
    "CDN_PURGE_PATHS",
)


def redact_secrets(text: str) -> str:
    """Replace configured secret values before anything is printed."""
    secrets: list[str] = []
    for name in _SECRET_ENV:
        raw = os.environ.get(name, "").strip()
        parts = [raw]
        if name == "CDN_PURGE_PATHS":
            parts.extend(part.strip() for part in raw.split(","))
        for part in parts:
            if len(part) < 8:
                continue
            secrets.append(part)
            encoded = quote(part, safe="")
            if encoded != part:
                secrets.append(encoded)
    redacted = text
    for secret in sorted(set(secrets), key=len, reverse=True):
        redacted = redacted.replace(secret, "***")
    return redacted
