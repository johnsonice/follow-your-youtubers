from __future__ import annotations

import json

import pytest

import net
from ytdlp_subs import parse_json3


def test_proxy_precedence(monkeypatch):
    assert net.proxy_url() is None
    monkeypatch.setenv("HTTPS_PROXY", "http://b:1")
    assert net.proxy_url() == "http://b:1"
    monkeypatch.setenv("YT_PROXY", "http://a:1")
    assert net.proxy_url() == "http://a:1"


def test_retry_with_backoff_retries_then_succeeds():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("blip")
        return "ok"

    assert net.retry_with_backoff(fn, attempts=3, base_delay=1, sleep=sleeps.append) == "ok"
    assert len(sleeps) == 2 and sleeps[1] >= 2


def test_retry_stops_on_non_retryable():
    def fn():
        raise RuntimeError("IpBlocked")

    with pytest.raises(RuntimeError):
        net.retry_with_backoff(
            fn, attempts=3, should_retry=lambda e: not net.is_block_error(e),
            sleep=lambda s: pytest.fail("should not sleep"),
        )


def test_log_skipped_appends_jsonl(tmp_path):
    p = tmp_path / "s.jsonl"
    net.log_skipped("abc", "ip_blocked", "IpBlocked", path=p)
    net.log_skipped("def", "no_captions", "x", path=p)
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    assert [r["video_id"] for r in rows] == ["abc", "def"]


def test_parse_json3():
    data = {"events": [{"tStartMs": 1000, "dDurationMs": 500, "segs": [{"utf8": "hi "}, {"utf8": "there"}]},
                       {"tStartMs": 2000}, {"segs": [{"utf8": "\n"}]}]}
    out = parse_json3(data)
    assert len(out) == 1 and out[0].text == "hi there" and out[0].start == 1.0


def test_transcribe_falls_back_to_ytdlp_when_blocked(monkeypatch):
    import fetch
    from core import Snippet, TranscriptError

    def blocked(*a, **k):
        raise TranscriptError(kind="ip_blocked", detail="IpBlocked")

    monkeypatch.setattr(fetch, "yt_object", blocked)
    monkeypatch.setattr(fetch, "try_captions", blocked)
    monkeypatch.setattr(fetch, "try_ytdlp_subs", lambda v, l: ("en", [Snippet("hi", 0.0, 1.0)]))
    res = fetch.transcribe("dQw4w9WgXcQ", languages=None, allow_whisper=False)
    assert res.source == "captions" and res.snippets[0].text == "hi"


def test_cli_logs_skipped_video(monkeypatch, tmp_path, capsys):
    import fetch
    from core import TranscriptError

    def blocked(*a, **k):
        raise TranscriptError(kind="ip_blocked", detail="IpBlocked")

    monkeypatch.setattr(fetch, "transcribe", blocked)
    assert fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ"]) == 1
    rows = (tmp_path / "skipped.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["video_id"] == "dQw4w9WgXcQ"
