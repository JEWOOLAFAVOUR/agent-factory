
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote, urlparse, urlunparse

import feedparser
import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool


load_dotenv()


GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
BLUESKY_SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
X_SEARCH_URL = (
    "https://api.twitterapis.com/twitter/tweet/advanced_search"
)


def clean_text(value: str) -> str:
    """Remove HTML and normalize whitespace."""
    value = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return " ".join(value.split())


def normalize_url(url: str) -> str:
    """Normalize URL for dedup (strip tracking, trailing slash, case)."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlparse(url)
        # Drop common tracking params, keep path + core query.
        host = parts.netloc.lower()
        path = parts.path.rstrip("/") or "/"
        return urlunparse((parts.scheme.lower(), host, path, "", "", ""))
    except ValueError:
        return url.lower()


def normalize_title(title: str) -> str:
    """Normalize title for cross-source dedup."""
    title = clean_text(title).lower()
    title = re.sub(r"\s*[-|–—:]\s*[^-|–—:]{1,60}$", "", title).strip()
    return re.sub(r"[^a-z0-9 ]+", "", title).strip()


def parse_published(value: str) -> datetime | None:
    """Parse RSS / ISO timestamps into aware datetimes."""
    if not value:
        return None
    text = value.strip()
    # ISO 8601 (Bluesky, X).
    try:
        if "T" in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # RFC 2822 (Google News RSS).
    try:
        dt = parsedate_to_datetime(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def within_days(published: str, days: int) -> bool:
    """Check story is inside the requested news window."""
    dt = parse_published(published)
    if dt is None:
        return True  # Keep undated items, flag as Unknown downstream.
    now = datetime.now(timezone.utc)
    # Small 6h grace for clock skew / feed lag.
    return dt >= now - timedelta(days=days, hours=6)


def fetch_google_news(
    client: httpx.Client, topic: str, days: int
) -> list[dict]:
    """Retrieve article metadata from Google News RSS."""
    response = client.get(
        GOOGLE_NEWS_URL,
        params={
            "q": f"{topic} when:{days}d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        },
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if feed.bozo:
        return []

    results = []

    for entry in feed.entries:
        source = entry.get("source", {}).get(
            "title", "Google News publisher"
        )

        results.append(
            {
                "title": clean_text(entry.get("title", "")),
                "text": clean_text(entry.get("summary", "")),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": source,
                "source_type": "news",
                "engagement": 0,
            }
        )

    return results


def fetch_bluesky_posts(
    client: httpx.Client, topic: str, limit: int
) -> list[dict]:
    """Search public Bluesky posts."""
    response = client.get(
        BLUESKY_SEARCH_URL,
        params={"q": topic, "limit": min(limit, 25), "sort": "latest"},
    )
    response.raise_for_status()

    payload = response.json()
    results = []

    for post in payload.get("posts", []):
        record = post.get("record", {})
        author = post.get("author", {})
        uri = post.get("uri", "")
        parts = uri.split("/")

        post_url = ""
        if len(parts) >= 3:
            handle = author.get("handle", "")
            post_id = parts[-1]
            if handle and post_id:
                post_url = (
                    f"https://bsky.app/profile/{handle}/post/{post_id}"
                )

        text = clean_text(record.get("text", ""))

        results.append(
            {
                "title": text[:160] or "Bluesky post",
                "text": text,
                "url": post_url,
                "published": record.get("createdAt", ""),
                "source": f"Bluesky @{author.get('handle', 'unknown')}",
                "source_type": "social",
                "engagement": (
                    post.get("likeCount", 0)
                    + post.get("repostCount", 0) * 2
                    + post.get("replyCount", 0)
                ),
            }
        )

    return results


def fetch_x_posts(
    client: httpx.Client, topic: str, limit: int
) -> list[dict]:
    """Search X using an optional third-party API key."""
    api_key = os.getenv("TWITTERAPIS_KEY")

    if not api_key:
        return []

    response = client.get(
        X_SEARCH_URL,
        params={
            "query": topic,
            "product": "Latest",
            "count": min(limit, 20),
            "compact": "1",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    response.raise_for_status()

    payload = response.json()
    results = []

    for post in payload.get("tweets", []):
        author = post.get("author", {})
        username = author.get("username", "")
        post_id = post.get("id", "")
        url = post.get("url", "")

        if not url and username and post_id:
            url = f"https://x.com/{username}/status/{post_id}"

        text = clean_text(post.get("text", ""))

        results.append(
            {
                "title": text[:160] or "X post",
                "text": text,
                "url": url,
                "published": post.get("created_at", ""),
                "source": f"X @{username or 'unknown'}",
                "source_type": "social",
                "engagement": (
                    post.get("favorite_count", 0)
                    + post.get("retweet_count", 0) * 2
                    + post.get("reply_count", 0)
                ),
            }
        )

    return results


def rank_results(items: list[dict], days: int = 7) -> list[dict]:
    """Dedup by normalized URL + title, filter by date, then rank."""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique = []

    for item in items:
        if not within_days(item.get("published", ""), days):
            continue

        url_key = normalize_url(item.get("url", ""))
        title_key = normalize_title(item.get("title", ""))
        if (url_key and url_key in seen_urls) or (
            title_key and title_key in seen_titles
        ):
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)

        text = f"{item['title']} {item['text']}".lower()

        # A transparent heuristic, not an AI truth detector.
        relevance = sum(
            weight
            for phrase, weight in [
                ("open source", 3),
                ("ai agent", 3),
                ("artificial intelligence", 2),
                ("launch", 1),
                ("release", 1),
                ("developer", 1),
                ("funding", 1),
                ("security", 1),
            ]
            if phrase in text
        )

        engagement = max(0, item.get("engagement", 0))
        engagement_points = min(engagement, 100) / 25

        source_points = 2 if item["source_type"] == "news" else 1

        # Recency boost: <24h +1, <72h +0.5 (parsed dates only).
        dt = parse_published(item.get("published", ""))
        recency = 0.0
        if dt is not None:
            age_h = (
                datetime.now(timezone.utc) - dt
            ).total_seconds() / 3600
            if age_h <= 24:
                recency = 1.0
            elif age_h <= 72:
                recency = 0.5

        item["score"] = round(
            relevance + engagement_points + source_points + recency, 2
        )
        unique.append(item)

    return sorted(
        unique,
        key=lambda item: item["score"],
        reverse=True,
    )


def search_news_items(
    topic: str, days: int = 1, limit: int = 8
) -> tuple[list[dict], dict[str, str]]:
    """Structured fetch used by the agent tool, CLI, and the Worker.

    Returns (ranked_items, source_status). Raises ValueError on bad input.
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic cannot be empty.")
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7.")
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10.")

    all_results: list[dict] = []
    source_status: dict[str, str] = {}

    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "NewUpdater/0.1"},
    ) as client:
        sources = [
            (
                "Google News",
                lambda: fetch_google_news(client, topic, days),
            ),
            (
                "Bluesky",
                lambda: fetch_bluesky_posts(client, topic, 25),
            ),
        ]

        if os.getenv("TWITTERAPIS_KEY"):
            sources.append(
                ("X", lambda: fetch_x_posts(client, topic, 20))
            )
        else:
            source_status["X"] = (
                "Not configured; set TWITTERAPIS_KEY to enable it."
            )

        for source_name, fetch in sources:
            try:
                results = fetch()
                all_results.extend(results)
                source_status[source_name] = (
                    f"{len(results)} result(s)"
                )
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                source_status[source_name] = (
                    f"Unavailable ({type(exc).__name__})"
                )

    return rank_results(all_results, days=days)[:limit], source_status


@tool
def search_news(
    topic: str, days: int = 1, limit: int = 8
) -> str:
    """Search news and social sources for recent technology developments.

    Args:
        topic: Search topic, company, technology, or industry.
        days: Requested news window, from 1 to 7 days.
        limit: Maximum number of ranked results, from 1 to 10.
    """
    try:
        ranked, source_status = search_news_items(topic, days, limit)
    except ValueError as exc:
        return f"Search failed: {exc}"
    except httpx.HTTPError as exc:
        return f"Search setup failed: {type(exc).__name__}"

    topic = (topic or "").strip()
    if not ranked:
        status = "\n".join(
            f"- {name}: {state}"
            for name, state in source_status.items()
        )
        return (
            f"No results found for '{topic}'.\n"
            f"Source status:\n{status}"
        )

    lines = [
        f"Research results for: {topic}",
        f"Requested news window: {days} day(s)",
        "Ranking: relevance heuristic, engagement, and source type.",
        "Note: social posts are leads, not independently verified facts.",
        "",
        "Source status:",
    ]

    for name, state in source_status.items():
        lines.append(f"- {name}: {state}")

    lines.append("")

    for index, item in enumerate(ranked, start=1):
        lines.append(
            f"{index}. {item['title']}\n"
            f"   Source: {item['source']} ({item['source_type']})\n"
            f"   Published: {item['published'] or 'Unknown'}\n"
            f"   Relevance score: {item['score']}\n"
            f"   Details: {item['text'] or 'No snippet available.'}\n"
            f"   Link: {item['url'] or 'No direct link available.'}"
        )

    return "\n\n".join(lines)