#!/usr/bin/env python3
"""Upload the generated market tree to Tencent COS, then refresh CDN.

Data files go up first. Each ``index.json`` is uploaded after its scope, because
the index is the visibility switch. A successful upload then calls CDN
PurgePathCache for the plugins and experts directories.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from env_file import load_env, redact_secrets
from purge_cdn import purge_market_cache


def endpoint(bucket: str, region: str) -> str:
    """Public COS host, unless COS_ENDPOINT overrides it.

    GitHub-hosted runners cannot reach ``cos-internal``. A VPC upload can set
    COS_ENDPOINT to ``{bucket}.cos-internal.{region}.tencentcos.cn``.
    """
    configured = os.environ.get("COS_ENDPOINT", "").strip()
    host = configured or f"{bucket}.cos.{region}.myqcloud.com"
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host.strip("/")


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing {name}; copy .env.example to .env and fill it")
    return value


def purge_enabled() -> bool:
    return os.environ.get("CDN_PURGE", "1").strip().lower() not in {"0", "false", "no"}


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_env(repo_root / ".env")

    coscli = shutil.which("coscli")
    if not coscli:
        raise SystemExit("coscli is not installed or is not on PATH")

    secret_id = required("COS_SECRET_ID")
    secret_key = required("COS_SECRET_KEY")
    bucket = required("COS_BUCKET")
    region = required("COS_REGION")
    host = endpoint(bucket, region)
    token = os.environ.get("COS_SESSION_TOKEN", "").strip()
    market = repo_root / "octop" / "market"
    if not (market / "plugins" / "index.json").is_file():
        raise SystemExit("octop/market is missing; run scripts/build-market.py first")
    if not (market / "experts" / "index.json").is_file():
        raise SystemExit("octop/market/experts/index.json is missing; run scripts/build-market.py first")

    common = [
        "-e",
        host,
        "--customized",
        "--close_auto_switch_host",
        "true",
        "-i",
        secret_id,
        "-k",
        secret_key,
        "--init-skip",
        "--disable-log=true",
        "--process-log=false",
        "--fail-output=false",
    ]
    if token:
        common.extend(["--token", token])

    # Publish the data first. An index is the visibility switch for its scope.
    for scope in ("plugins", "experts"):
        source = f"{market / scope}/"
        target = f"cos://{bucket}/octop/market/{scope}/"
        print(f"upload {scope}")
        run([coscli, "cp", "-r", source, target, "--exclude", "index.json", *common])
    for scope in ("plugins", "experts"):
        source = str(market / scope / "index.json")
        target = f"cos://{bucket}/octop/market/{scope}/index.json"
        print(f"upload {scope} index")
        run([coscli, "cp", source, target, *common])

    print("uploaded market")
    if purge_enabled():
        purge_market_cache()
    return 0


def run(command: list[str]) -> None:
    # The command line holds COS credentials, so keep it out of logs and tracebacks.
    result = subprocess.run(command, check=False, capture_output=True)
    output = redact_secrets(_output_text(result.stdout) + _output_text(result.stderr)).strip()
    if output:
        print(output)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _output_text(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


if __name__ == "__main__":
    sys.exit(main())
