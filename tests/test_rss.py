"""Unit tests for scripts/rss.py — fixture-driven, no network."""
from __future__ import annotations

import pytest

from core import TranscriptError
from rss import extract_channel_id, parse_feed

CHANNEL_PAGE_HTML = """
<html><head>
<link rel="canonical" href="https://www.youtube.com/channel/UCK7tptUDHh-RYDsdxO1-5QQ">
</head><body></body></html>
"""

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Example Channel</title>
  <entry>
    <yt:videoId>abc123XYZ00</yt:videoId>
    <title>First video</title>
    <published>2026-07-01T12:00:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123XYZ00"/>
  </entry>
  <entry>
    <yt:videoId>def456UVW11</yt:videoId>
    <title>Second video</title>
    <published>2026-06-30T09:30:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/watch?v=def456UVW11"/>
  </entry>
</feed>
"""


def test_extract_channel_id_from_canonical_link() -> None:
    assert extract_channel_id(CHANNEL_PAGE_HTML) == "UCK7tptUDHh-RYDsdxO1-5QQ"


def test_extract_channel_id_missing_raises_exit_1() -> None:
    with pytest.raises(TranscriptError) as exc:
        extract_channel_id("<html>no id here</html>")
    assert exc.value.exit_code == 1
    assert exc.value.kind == "channel_id_not_found"


def test_parse_feed_returns_entries_in_feed_order() -> None:
    results = parse_feed(FEED_XML)
    assert [r["video_id"] for r in results] == ["abc123XYZ00", "def456UVW11"]
    first = results[0]
    assert first["title"] == "First video"
    assert first["published"] == "2026-07-01T12:00:00+00:00"
    assert first["url"] == "https://www.youtube.com/watch?v=abc123XYZ00"


def test_parse_feed_skips_entry_missing_video_id() -> None:
    broken = FEED_XML.replace("<yt:videoId>abc123XYZ00</yt:videoId>", "", 1)
    results = parse_feed(broken)
    assert [r["video_id"] for r in results] == ["def456UVW11"]


def test_parse_feed_invalid_xml_raises_exit_1() -> None:
    with pytest.raises(TranscriptError) as exc:
        parse_feed("this is not xml <")
    assert exc.value.exit_code == 1
    assert exc.value.kind == "rss_parse_failed"
