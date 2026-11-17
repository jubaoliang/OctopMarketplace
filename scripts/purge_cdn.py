#!/usr/bin/env python3
"""Refresh CDN directories with PurgePathCache.

https://cloud.tencent.com/document/product/228/37871

Directory URLs come from ``CDN_PURGE_PATHS``. ``flush`` marks updated objects
stale. ``delete`` drops every cached object under the directory. Credentials
fall back to the COS secret pair. A temporary key also needs its session token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from env_file import load_env, redact_secrets

SERVICE = "cdn"
HOST = "cdn.tencentcloudapi.com"
ACTION = "PurgePathCache"
VERSION = "2018-06-06"
ALGORITHM = "TC3-HMAC-SHA256"
CONTENT_TYPE = "application/json; charset=utf-8"


def purge_market_cache() -> str:
    """Submit one directory purge and return its TaskId."""
    secret_id, secret_key, token = credentials()
    flush_type = cdn_flush_type()
    body: dict[str, object] = {"Paths": purge_paths(), "FlushType": flush_type}
    area = os.environ.get("CDN_PURGE_AREA", "").strip()
    if area:
        if area not in {"mainland", "overseas"}:
            raise SystemExit("CDN_PURGE_AREA must be mainland or overseas")
        body["Area"] = area
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = tc3_headers(secret_id, secret_key, token, payload)
    request = urllib.request.Request(
        f"https://{HOST}/",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise SystemExit(redact_secrets(f"PurgePathCache request failed: {exc}")) from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(redact_secrets(f"PurgePathCache returned non-JSON: {exc}")) from exc
    response_body = parsed.get("Response") if isinstance(parsed, dict) else None
    if not isinstance(response_body, dict):
        raise SystemExit("PurgePathCache response has no Response object")
    error = response_body.get("Error")
    request_id = response_body.get("RequestId") or ""
    if isinstance(error, dict):
        code = error.get("Code") or "Error"
        message = error.get("Message") or ""
        detail = redact_secrets(f"PurgePathCache {code}: {message} RequestId={request_id}")
        raise SystemExit(detail)
    task_id = str(response_body.get("TaskId") or "")
    if not task_id:
        raise SystemExit(f"PurgePathCache returned no TaskId RequestId={request_id}")
    print(
        f"purged CDN TaskId={task_id} RequestId={request_id} "
        f"paths={len(body['Paths'])} FlushType={flush_type}"
    )
    return task_id


def credentials() -> tuple[str, str, str]:
    secret_id = os.environ.get("CDN_SECRET_ID", "").strip() or os.environ.get("COS_SECRET_ID", "").strip()
    secret_key = os.environ.get("CDN_SECRET_KEY", "").strip() or os.environ.get("COS_SECRET_KEY", "").strip()
    token = os.environ.get("CDN_SESSION_TOKEN", "").strip() or os.environ.get("COS_SESSION_TOKEN", "").strip()
    if not secret_id or not secret_key:
        raise SystemExit("missing CDN_SECRET_ID/CDN_SECRET_KEY or COS_SECRET_ID/COS_SECRET_KEY")
    return secret_id, secret_key, token


def purge_paths() -> list[str]:
    raw = os.environ.get("CDN_PURGE_PATHS", "").strip()
    if not raw:
        raise SystemExit("missing CDN_PURGE_PATHS")
    items = [part.strip() for part in raw.split(",") if part.strip()]
    paths: list[str] = []
    for item in items:
        if not item.startswith(("http://", "https://")):
            raise SystemExit("CDN purge path must include http:// or https://")
        if not item.endswith("/"):
            item = f"{item}/"
        paths.append(item)
    if not paths:
        raise SystemExit("no CDN purge paths")
    if len(paths) > 500:
        raise SystemExit("PurgePathCache accepts at most 500 paths per request")
    return paths


def cdn_flush_type() -> str:
    value = os.environ.get("CDN_FLUSH_TYPE", "flush").strip() or "flush"
    if value not in {"flush", "delete"}:
        raise SystemExit("CDN_FLUSH_TYPE must be flush or delete")
    return value


def tc3_headers(secret_id: str, secret_key: str, token: str, payload: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Build TC3-HMAC-SHA256 headers. The signed payload bytes are the request body."""
    signed_at = int(timestamp if timestamp is not None else datetime.now(timezone.utc).timestamp())
    date = datetime.fromtimestamp(signed_at, timezone.utc).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:{CONTENT_TYPE}\nhost:{HOST}\nx-tc-action:{ACTION.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = "\n".join(
        [
            "POST",
            "/",
            "",
            canonical_headers,
            signed_headers,
            hashed_payload,
        ]
    )
    scope = f"{date}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            str(signed_at),
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, SERVICE)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": (
            f"{ALGORITHM} Credential={secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "Content-Type": CONTENT_TYPE,
        "Host": HOST,
        "X-TC-Action": ACTION,
        "X-TC-Timestamp": str(signed_at),
        "X-TC-Version": VERSION,
    }
    if token:
        headers["X-TC-Token"] = token
    return headers


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def self_check() -> None:
    """Check the signer against a fixed PurgePathCache body."""
    body = {
        "Paths": [
            "https://cdn.example/market/plugins/",
            "https://cdn.example/market/experts/",
        ],
        "FlushType": "flush",
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = tc3_headers("AKIDEXAMPLE", "SECRETKEYEXAMPLE", "", payload, timestamp=1551113065)
    signature = headers["Authorization"].rsplit("Signature=", 1)[-1]
    expected = "f48e3649c3f307e9033db770848850f391431ef5e3ae1441969178f9d280e15b"
    if signature != expected:
        raise SystemExit("signature self-check failed")
    if headers["X-TC-Action"] != ACTION or headers["Content-Type"] != CONTENT_TYPE:
        raise SystemExit("signature self-check header mismatch")
    print("signature self-check ok")


def main() -> int:
    if "--self-check" in sys.argv:
        self_check()
        return 0
    repo_root = Path(__file__).resolve().parents[1]
    load_env(repo_root / ".env")
    purge_market_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
