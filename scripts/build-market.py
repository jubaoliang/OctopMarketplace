#!/usr/bin/env python3
"""Build the public COS tree from this catalog.

Reads ``plugins/`` and ``experts/`` in this repository and writes objects under
``<out>/octop/market/``. Upload that directory onto the bucket behind
https://download.octop.cloud so each object key matches the relative path.

Object layout matches the octop-market importer: zip, icon, and ``meta.json``
under ``{id}/{version}/``, with ``index.json`` as the visibility switch.
An expert avatar is ``avatar.png`` or ``avatar.jpg`` in that expert directory.
The blank ``default`` template is omitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from env_file import load_env

CDN_BASE = "https://download.octop.cloud"
MARKET_ROOT = "octop/market"
EXPERT_VERSION = "1.0.0"
CONTENT_MAX = 8000
META_MAX_BYTES = 256 * 1024
SKIP_EXPERTS = {"default"}

# Library manifests do not declare a market scene. These slugs match the
# portal scene list in src/lib/market/taxonomy.ts.
EXPERT_SCENES = {
    "ai-coding-coach": "education",
    "ai-safety-guardian": "tech",
    "business-operations": "hr",
    "clinical-learning-subscription": "healthcare",
    "cowork-plugin-management": "tech",
    "cvm-ai-doctor": "tech",
    "cvm-cluster-doctor": "tech",
    "design": "design",
    "engineering": "tech",
    "karpathy-knowledge-base": "academic",
    "meituan-living-assistant": "lifestyle",
    "multi-agent-orchestrator": "tech",
    "news-trend": "media",
    "office-automation": "hr",
    "ops-engineer": "tech",
    "parenting-companion": "lifestyle",
    "productivity": "hr",
    "stock-assistant": "finance",
    "superpowers-methodology": "education",
    "tencentcloud-api": "tech",
    "wechat-ops": "content-creation",
}

# plugin.yaml is Chinese. The portal switches these with the site language.
PLUGIN_EN: dict[str, tuple[str, str]] = {
    "air-quality": ("Air Quality", "Look up a city's PM2.5 and AQI."),
    "arxiv-search": (
        "arXiv Search",
        "Look up arXiv paper titles, authors, abstracts, and links. No API key.",
    ),
    "bilibili-anime": (
        "Bilibili Anime",
        "Search Bilibili anime in chat, and play or switch episodes.",
    ),
    "color-convert": ("Color Convert", "Convert colors between HEX, RGB, and HSL."),
    "daily-english": (
        "Daily English",
        "A word a day, with pronunciation, definition, and an example.",
    ),
    "fortune": ("Fortune", "Roll dice, draw a lot, or see today's fortune as a chat card."),
    "fun-facts": ("Fun Facts", "Random trivia and light jokes."),
    "github-trending": (
        "GitHub Trending",
        "Browse rising GitHub repositories by language and time range.",
    ),
    "hot-topics": (
        "Hot Topics",
        "Weibo, Zhihu, and Hacker News hot lists as a clickable chat card.",
    ),
    "ip-lookup": ("IP Lookup", "Look up an IP address location and ISP."),
    "market-quotes": (
        "Market Quotes",
        "Exchange rates, crypto prices, and A-share quote cards.",
    ),
    "meme-maker": ("Meme Maker", "Generate memes with memegen.link."),
    "mini-games": (
        "Mini Games",
        "Tic-tac-toe and number guessing, with a board and hints in chat.",
    ),
    "movie-search": ("Movie Search", "Search anime and film entries on Bangumi."),
    "parcel-tracker": (
        "Parcel Tracker",
        "Track domestic parcels, with a kuaidi100 link when lookup fails.",
    ),
    "pomodoro": ("Pomodoro", "Start a Pomodoro timer or countdown card in chat."),
    "qrcode": ("QR Code", "Turn text or a link into a QR code card."),
    "server-status": (
        "Server Status",
        "Show this server's OS, kernel, and CPU, memory, and disk load in chat.",
    ),
    "short-link": ("Short Link", "Shorten a long URL with is.gd."),
    "slack-calendar": (
        "Slacking Calendar",
        "Countdown to the weekend and holidays, plus today's slacking tips.",
    ),
    "sports-scores": (
        "Sports Scores",
        "Recent scores for leagues such as the Premier League (TheSportsDB).",
    ),
    "tetris": ("Tetris", "Play Tetris in a chat card, with keyboard and button controls."),
    "travel-inspire": ("Travel Ideas", "Suggest destinations and the best season by mood."),
    "unit-convert": ("Unit Convert", "Convert length, mass, and temperature."),
    "weather": ("Weather", "City weather and forecasts, shown as a chat card."),
    "what-to-eat": ("What to Eat", "Suggest a dish by meal and taste."),
    "wiki-summary": ("Wiki Summary", "Read a Wikipedia article summary."),
}

ICON_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}
AVATAR_SUFFIXES = (".svg", ".avif", ".png", ".webp", ".jpg", ".jpeg", ".gif")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    load_env(repo_root / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=".",
        help="Directory that will contain octop/market/. Default: this repository.",
    )
    args = parser.parse_args()
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = (repo_root / out_root).resolve()
    plugins_root, experts_root, avatars_root = catalog_roots(repo_root)
    if not plugins_root.is_dir() or not experts_root.is_dir():
        print(f"catalog not found under {repo_root}", file=sys.stderr)
        return 1
    market = out_root / MARKET_ROOT
    if market.exists():
        remove_tree(market)
    market.mkdir(parents=True)

    plugin_ids = build_plugins(plugins_root, market)
    expert_ids = build_experts(experts_root, avatars_root, market)
    write_json(market / "plugins" / "index.json", plugin_ids)
    write_json(market / "experts" / "index.json", expert_ids)
    print(f"plugins {len(plugin_ids)}")
    print(f"experts {len(expert_ids)}")
    print(market)
    return 0


def catalog_roots(repo_root: Path) -> tuple[Path, Path, Path]:
    """Return this catalog's plugin, expert, and avatar directories.

    ``avatar.png`` or ``avatar.jpg`` lives in the expert directory. ``assets/avatars``
    remains a fallback for an old ``/experts/avatars/<file>`` path.
    """
    return (
        repo_root / "plugins",
        repo_root / "experts",
        repo_root / "assets" / "avatars",
    )


def build_plugins(plugins_root: Path, market: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for directory in sorted(path for path in plugins_root.iterdir() if path.is_dir()):
        manifest_path = directory / "plugin.yaml"
        if not manifest_path.is_file():
            continue
        raw = parse_simple_yaml(manifest_path.read_text(encoding="utf-8"))
        plugin_id = str(raw.get("id") or "").strip()
        version = str(raw.get("version") or "").strip()
        if plugin_id != directory.name:
            raise SystemExit(f"{manifest_path}: id {plugin_id!r} does not match {directory.name}")
        if not version:
            raise SystemExit(f"{manifest_path}: missing version")
        files = list_files(directory)
        dest = market / "plugins" / plugin_id
        version_dir = dest / version
        version_dir.mkdir(parents=True)
        archive_path = version_dir / f"{plugin_id}-{version}.zip"
        write_zip(archive_path, directory, files)
        icon_url = publish_plugin_icon(version_dir, directory, raw.get("icon"), plugin_id, version)
        stat = archive_path.stat()
        zh_name = str(raw.get("name") or plugin_id).strip() or plugin_id
        zh_description = str(raw.get("description") or "").strip()
        en_name, en_description = PLUGIN_EN.get(plugin_id, ("", ""))
        if not en_name:
            print(f"plugin {plugin_id}: missing English name and description", file=sys.stderr)
            en_name, en_description = zh_name, zh_description
        write_json(
            version_dir / "meta.json",
            {
                "version": version,
                "name": {"zh": zh_name, "en": en_name},
                "kind": str(raw.get("kind") or "tool").strip() or "tool",
                "description": {"zh": zh_description, "en": en_description},
                "icon": icon_url,
                "group": str(raw.get("group") or "").strip().lower(),
                "requires": string_list(raw.get("requires")),
                "size_bytes": stat.st_size,
                "sha256": sha256(archive_path),
                "updated_at": iso_from_mtime(newest_mtime([manifest_path, *files])),
            },
        )
        entries.append({"slug": plugin_id, "version": version})
        print(f"plugin {plugin_id} {version} {stat.st_size} bytes {len(files)} files")
    return entries


def build_experts(experts_root: Path, avatars_root: Path, market: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for directory in sorted(path for path in experts_root.iterdir() if path.is_dir()):
        if directory.name in SKIP_EXPERTS:
            print(f"expert skip {directory.name}")
            continue
        if not (directory / "manifest.json").is_file():
            continue
        entries.append(export_expert(directory, avatars_root, market))
    return entries


def expert_sub_scene(raw: dict[str, object]) -> str:
    """Finer scene from the manifest. SkillHub stores it beside ``scene``."""
    text = str(raw.get("sub_scene") or "").strip()
    if text:
        return text
    for key in ("source", "skillhub"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            text = str(nested.get("sub_scene") or "").strip()
            if text:
                return text
    return ""


def expert_scene(raw: dict[str, object], slug: str) -> str:
    """Portal scene. Manifest content wins over the builtin slug map."""
    scene = str(raw.get("scene") or "").strip()
    if not scene:
        source = raw.get("source")
        if isinstance(source, dict):
            scene = str(source.get("scene") or "").strip()
    if not scene:
        skillhub = raw.get("skillhub")
        if isinstance(skillhub, dict):
            scene = str(skillhub.get("scene") or "").strip()
    return scene or EXPERT_SCENES.get(slug, "")


def expert_version(raw: dict[str, object]) -> str:
    """Single path segment for ``experts/{slug}/{version}/``.

    ``manifest.json`` ``version`` wins. A missing field falls back to ``1.0.0``.
    """
    version = str(raw.get("version") or EXPERT_VERSION).strip() or EXPERT_VERSION
    if version in {".", ".."} or "/" in version or "\\" in version:
        raise SystemExit(f"expert version must be one path segment, got {version!r}")
    return version


def export_expert(directory: Path, avatars_root: Path, market: Path) -> dict[str, str]:
    """Write one expert version directory and return its index entry."""
    manifest_path = directory / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit(f"{manifest_path}: manifest is not an object")
    slug = str(raw.get("id") or "").strip()
    if slug != directory.name:
        raise SystemExit(f"{manifest_path}: id {slug!r} does not match {directory.name}")
    version = expert_version(raw)
    files = list_files(directory)
    version_dir = market / "experts" / slug / version
    version_dir.mkdir(parents=True)
    archive_path = version_dir / f"{slug}-{version}.zip"
    write_zip(archive_path, directory, files)
    stat = archive_path.stat()
    meta: dict[str, object] = {
        "version": version,
        "label": localized(raw.get("label"), slug),
        "description": localized(raw.get("description"), ""),
        "size_bytes": stat.st_size,
        "sha256": sha256(archive_path),
        "updated_at": iso_from_mtime(newest_mtime([manifest_path, *files])),
    }
    welcome = localized(raw.get("welcome_message"), "")
    if welcome["zh"] or welcome["en"]:
        meta["welcome_message"] = welcome
    scene = expert_scene(raw, slug)
    if scene:
        meta["scene"] = scene
    sub_scene = expert_sub_scene(raw)
    if sub_scene:
        meta["sub_scene"] = sub_scene
    icon_url = publish_expert_avatar(
        version_dir, avatars_root, slug, version, raw.get("icon_url"), directory
    )
    if icon_url:
        meta["icon_url"] = icon_url
    icon_name = str(raw.get("icon_name") or "").strip()
    if icon_name:
        meta["icon_name"] = icon_name
    color = str(raw.get("color") or "").strip()
    if color:
        meta["color"] = color
    skill_slugs = skill_dirs(directory)
    if skill_slugs:
        meta["skill_slugs"] = skill_slugs
        meta["skill_count"] = len(skill_slugs)
    prompts = raw.get("quick_prompts")
    if isinstance(prompts, list) and prompts:
        meta["quick_prompts"] = prompts[:20]
    examples = raw.get("task_examples")
    if isinstance(examples, dict) and examples:
        meta["task_examples"] = examples
    content = expert_content(directory, raw.get("prompt_files"))
    if content:
        meta["content"] = content
    write_json(version_dir / "meta.json", meta)
    print(f"expert {slug} {version} {stat.st_size} bytes {len(files)} files")
    return {"slug": slug, "version": version}


def publish_plugin_icon(
    dest: Path,
    plugin_dir: Path,
    icon: object,
    plugin_id: str,
    version: str,
) -> str:
    text = str(icon or "").strip()
    if text.startswith(("http://", "https://")):
        return text
    relative = text.lstrip("/").replace("\\", "/")
    suffix = Path(relative).suffix.lower()
    if not relative or suffix not in ICON_SUFFIXES or ".." in relative.split("/"):
        return text
    source = plugin_dir / relative
    if not source.is_file():
        return ""
    filename = f"icon{suffix}"
    (dest / filename).write_bytes(source.read_bytes())
    return f"{CDN_BASE}/{MARKET_ROOT}/plugins/{plugin_id}/{version}/{filename}"


def publish_expert_avatar(
    dest: Path,
    avatars_root: Path,
    slug: str,
    version: str,
    icon_url: object,
    expert_dir: Path | None = None,
) -> str:
    source = packaged_avatar(expert_dir)
    if source is None:
        source = avatar_file(avatars_root, slug, icon_url)
    if source is None:
        return ""
    suffix = source.suffix.lower()
    if suffix not in ICON_SUFFIXES:
        return ""
    filename = f"avatar{suffix}"
    (dest / filename).write_bytes(source.read_bytes())
    return f"{CDN_BASE}/{MARKET_ROOT}/experts/{slug}/{version}/{filename}"


def packaged_avatar(expert_dir: Path | None) -> Path | None:
    """Return ``avatar.<ext>`` shipped inside the expert directory."""
    if expert_dir is None:
        return None
    for suffix in AVATAR_SUFFIXES:
        candidate = expert_dir / f"avatar{suffix}"
        if candidate.is_file():
            return candidate
    return None


def avatar_file(avatars_root: Path, slug: str, icon_url: object) -> Path | None:
    text = str(icon_url or "").strip()
    prefix = "/experts/avatars/"
    if text.startswith(prefix):
        name = text[len(prefix):]
        suffix = Path(name).suffix.lower()
        if (
            name
            and suffix in ICON_SUFFIXES
            and "/" not in name
            and "\\" not in name
            and name not in {".", ".."}
            and ".." not in name
        ):
            candidate = avatars_root / name
            if candidate.is_file():
                return candidate
    for suffix in AVATAR_SUFFIXES:
        candidate = avatars_root / f"{slug}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def expert_content(directory: Path, prompt_files: object) -> str:
    candidates = ["SOUL.md"]
    if isinstance(prompt_files, list):
        candidates.extend(str(item) for item in prompt_files)
    seen: set[str] = set()
    for name in candidates:
        relative = name.strip().replace("\\", "/")
        if not relative or relative in seen or "/" in relative or relative == "manifest.json":
            continue
        seen.add(relative)
        path = directory / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text[:CONTENT_MAX]
    return ""


def skill_dirs(directory: Path) -> list[str]:
    skills = directory / "skills"
    if not skills.is_dir():
        return []
    return sorted(path.name for path in skills.iterdir() if path.is_dir() and not path.name.startswith("."))


def list_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
            continue
        files.append(path)
    return files


def write_zip(archive_path: Path, directory: Path, files: list[Path]) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(directory).as_posix()
            if relative.startswith("/") or ".." in relative.split("/"):
                raise SystemExit(f"refusing zip path {relative}")
            archive.write(path, relative)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
    if any(name.startswith("/") or ".." in name.split("/") for name in names):
        raise SystemExit(f"{archive_path}: unsafe zip entry")


def parse_simple_yaml(text: str) -> dict[str, object]:
    """Read the flat plugin.yaml shape: scalars and one-level string lists."""
    data: dict[str, object] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line.startswith((" ", "\t")):
            index += 1
            continue
        if ":" not in line:
            index += 1
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        if rest in {"", "|", ">"}:
            items: list[str] = []
            index += 1
            while index < len(lines):
                item = lines[index]
                if item.strip() == "" or item.strip().startswith("#"):
                    index += 1
                    continue
                if not item.startswith((" ", "\t")):
                    break
                content = item.strip()
                if content.startswith("- "):
                    items.append(unquote(content[2:].strip()))
                    index += 1
                    continue
                break
            data[key] = items
            continue
        data[key] = unquote(rest)
        index += 1
    return data


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def localized(value: object, fallback: str) -> dict[str, str]:
    if isinstance(value, str):
        text = value.strip()
        return {"zh": text, "en": text}
    if isinstance(value, dict):
        zh = str(value.get("zh") or "").strip()
        en = str(value.get("en") or "").strip()
        if zh or en:
            return {"zh": zh, "en": en}
    text = fallback.strip()
    return {"zh": text, "en": text}


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if path.name == "meta.json" and len(encoded) > META_MAX_BYTES:
        raise SystemExit(f"{path}: meta.json is {len(encoded)} bytes, over {META_MAX_BYTES}")
    path.write_bytes(encoded)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def newest_mtime(paths: list[Path]) -> float:
    return max(path.stat().st_mtime for path in paths)


def iso_from_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())
