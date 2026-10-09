"""Local seen-story store (JSON) — Worker uses KV/D1 for the same job."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "seen.json"


def _key(url: str, title: str) -> str:
    raw = (url.strip().lower() or title.strip().lower()).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def load_seen(path: Path = DEFAULT_PATH) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (ValueError, OSError):
        return set()


def filter_unseen(
    items: list[dict], path: Path = DEFAULT_PATH
) -> list[dict]:
    seen = load_seen(path)
    fresh = [i for i in items if _key(i.get("url", ""), i.get("title", "")) not in seen]
    return fresh


def mark_seen(items: list[dict], path: Path = DEFAULT_PATH) -> int:
    seen = load_seen(path)
    before = len(seen)
    for i in items:
        seen.add(_key(i.get("url", ""), i.get("title", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen)))
    return len(seen) - before
