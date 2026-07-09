"""Free channel discovery via YouTube's public RSS feed.

Resolves an @handle to a channel ID by scraping the channel page's canonical
link, then reads https://www.youtube.com/feeds/videos.xml?channel_id=UC...
The feed carries the ~15 most recent uploads. Zero credits, no API key.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from core import TranscriptError

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
CHANNEL_URL_TEMPLATE = "https://www.youtube.com/{handle}"
CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})")
REQUEST_TIMEOUT_S = 30
_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

_ATOM = "{http://www.w3.org/2005/Atom}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"


def extract_channel_id(page_html: str) -> str:
    """Pull the UC... channel ID out of a channel page's HTML."""
    match = CHANNEL_ID_RE.search(page_html)
    if not match:
        raise TranscriptError(
            kind="channel_id_not_found",
            detail="Could not find a channel ID in the channel page HTML.",
            exit_code=1,
        )
    return match.group(1)


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Map a YouTube RSS feed document to transcriptapi-like result rows."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise TranscriptError(
            kind="rss_parse_failed",
            detail=f"Invalid RSS XML: {exc}",
            exit_code=1,
        ) from exc

    results: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry"):
        video_id = entry.findtext(f"{_YT}videoId")
        published = entry.findtext(f"{_ATOM}published")
        if not video_id or not published:
            continue
        link = entry.find(f"{_ATOM}link")
        url = (
            link.get("href")
            if link is not None and link.get("href")
            else f"https://www.youtube.com/watch?v={video_id}"
        )
        results.append(
            {
                "video_id": video_id,
                "title": entry.findtext(f"{_ATOM}title") or "",
                "published": published,
                "url": url,
            }
        )
    return results


def channel_latest(handle: str, limit: int | None = None) -> dict[str, Any]:  # pragma: no cover
    """Fetch a channel's recent uploads. Network wrapper around the pure parsers."""
    import requests

    handle = handle.strip()
    if not handle.startswith("@"):
        raise TranscriptError(
            kind="bad_channel_handle",
            detail=f"Channel handle must start with '@': {handle!r}",
            exit_code=3,
        )

    try:
        page = requests.get(
            CHANNEL_URL_TEMPLATE.format(handle=handle),
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": _BROWSER_UA},
        )
    except requests.RequestException as exc:
        raise TranscriptError(
            kind="channel_fetch_failed",
            detail=f"Network error fetching channel page: {exc}",
            exit_code=1,
        ) from exc
    if page.status_code == 404:
        raise TranscriptError(
            kind="channel_unavailable",
            detail=f"YouTube returned 404 for {handle}.",
            exit_code=2,
        )
    if not page.ok:
        raise TranscriptError(
            kind="channel_fetch_failed",
            detail=f"YouTube returned {page.status_code} for {handle}.",
            exit_code=1,
        )

    channel_id = extract_channel_id(page.text)

    try:
        feed = requests.get(
            RSS_URL_TEMPLATE.format(channel_id=channel_id), timeout=REQUEST_TIMEOUT_S
        )
    except requests.RequestException as exc:
        raise TranscriptError(
            kind="rss_fetch_failed",
            detail=f"Network error fetching RSS feed: {exc}",
            exit_code=1,
        ) from exc
    if not feed.ok:
        raise TranscriptError(
            kind="rss_fetch_failed",
            detail=f"RSS feed returned {feed.status_code}.",
            exit_code=1,
        )

    results = parse_feed(feed.text)
    if limit is not None:
        results = results[:limit]
    return {"channel": handle, "results": results}
