"""Unit tests for scripts/rss.py — fixture-driven, no network."""
from __future__ import annotations

import pytest

from core import TranscriptError
from rss import drop_shorts, extract_channel_id, parse_feed

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
  <entry>
    <yt:videoId>shrt789RST2</yt:videoId>
    <title>A short clip</title>
    <published>2026-06-29T08:00:00+00:00</published>
    <link rel="alternate" href="https://www.youtube.com/shorts/shrt789RST2"/>
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
    assert [r["video_id"] for r in results] == ["abc123XYZ00", "def456UVW11", "shrt789RST2"]
    first = results[0]
    assert first["title"] == "First video"
    assert first["published"] == "2026-07-01T12:00:00+00:00"
    assert first["url"] == "https://www.youtube.com/watch?v=abc123XYZ00"


def test_parse_feed_skips_entry_missing_video_id() -> None:
    broken = FEED_XML.replace("<yt:videoId>abc123XYZ00</yt:videoId>", "", 1)
    results = parse_feed(broken)
    assert [r["video_id"] for r in results] == ["def456UVW11", "shrt789RST2"]


def test_parse_feed_invalid_xml_raises_exit_1() -> None:
    with pytest.raises(TranscriptError) as exc:
        parse_feed("this is not xml <")
    assert exc.value.exit_code == 1
    assert exc.value.kind == "rss_parse_failed"


def test_parse_feed_flags_shorts_by_their_shorts_url() -> None:
    flags = {r["video_id"]: r["is_short"] for r in parse_feed(FEED_XML)}
    assert flags == {"abc123XYZ00": False, "def456UVW11": False, "shrt789RST2": True}


def test_drop_shorts_keeps_regular_videos_in_order_and_counts_skipped() -> None:
    results = parse_feed(FEED_XML)

    kept, skipped = drop_shorts(results)

    assert [r["video_id"] for r in kept] == ["abc123XYZ00", "def456UVW11"]
    assert skipped == 1
    assert len(results) == 3  # input list is not mutated


def test_drop_shorts_with_no_shorts_skips_nothing() -> None:
    results = parse_feed(FEED_XML)[:2]

    kept, skipped = drop_shorts(results)

    assert kept == results
    assert skipped == 0
