"""Format ranked stories for Telegram (HTML, <4096 chars)."""

from __future__ import annotations

import html


def escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_digest(topic: str, items: list[dict], window: str = "") -> str:
    header = f"<b>NewUpdater — {escape(topic)}</b>"
    if window:
        header += f"\n<i>{escape(window)}</i>"
    header += "\n<i>Social posts are leads, not verified facts.</i>\n"

    blocks = [header]
    for i, item in enumerate(items, start=1):
        title = escape(item.get("title", "Untitled")[:160])
        source = escape(item.get("source", "unknown"))
        url = item.get("url", "")
        text = escape((item.get("text", "") or "")[:220])
        link = f'<a href="{escape(url)}">Read more</a>' if url else "No link"
        blocks.append(
            f"\n<b>{i}. {title}</b>\n"
            f"<i>{source} | {escape(item.get('published', '') or 'Unknown date')}</i>\n"
            f"{text}\n{link}"
        )

    out = "\n".join(blocks)
    # Telegram limit 4096 — hard truncate cleanly.
    if len(out) > 3900:
        out = out[:3900].rsplit("\n", 1)[0] + "\n\n<i>(truncated)</i>"
    return out
