"""CLI-level tests for scripts/fetch.py — dispatch and error contract, no network."""
from __future__ import annotations

import json

import pytest

import fetch
from core import Snippet, TranscriptError, TranscriptResult


def _out_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_no_subcommand_exits_3_with_json(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        fetch.main([])
    assert exc.value.code == 3
    assert _out_json(capsys)["error"] == "bad_args"


def test_latest_missing_channel_exits_3_with_json(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        fetch.main(["latest"])
    assert exc.value.code == 3
    assert _out_json(capsys)["error"] == "bad_args"


def test_latest_dispatches_and_prints_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        fetch,
        "channel_latest",
        lambda handle, limit=None: {"channel": handle, "results": [], "limit": limit},
    )
    rc = fetch.main(["latest", "--channel", "@example", "--limit", "3"])
    assert rc == 0
    assert _out_json(capsys) == {"channel": "@example", "results": [], "limit": 3}


def test_transcript_error_prints_json_and_exit_code(monkeypatch, capsys) -> None:
    def boom(video_url, *, languages, allow_whisper):
        raise TranscriptError(kind="no_captions", detail="none found", exit_code=2)

    monkeypatch.setattr(fetch, "transcribe", boom)
    rc = fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ", "--no-whisper"])
    assert rc == 2
    payload = _out_json(capsys)
    assert payload == {"error": "no_captions", "detail": "none found"}


def _fake_result() -> TranscriptResult:
    return TranscriptResult(
        video_id="dQw4w9WgXcQ",
        language="en",
        snippets=(Snippet(text="hello ", start=0.0, duration=1.0),
                  Snippet(text="world", start=1.0, duration=1.0)),
        metadata={"title": "T"},
        source="captions",
    )


def test_transcript_json_format(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        fetch, "transcribe", lambda v, *, languages, allow_whisper: _fake_result()
    )
    rc = fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ"])
    assert rc == 0
    payload = _out_json(capsys)
    assert payload["video_id"] == "dQw4w9WgXcQ"
    assert payload["source"] == "captions"
    assert payload["transcript"][0]["text"] == "hello "


def test_transcript_text_format_concatenates(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        fetch, "transcribe", lambda v, *, languages, allow_whisper: _fake_result()
    )
    rc = fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ", "--format", "text"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "hello world"


def test_transcript_language_flag_expands_zh(monkeypatch, capsys) -> None:
    captured: dict = {}

    def spy(video_url, *, languages, allow_whisper):
        captured["languages"] = languages
        return _fake_result()

    monkeypatch.setattr(fetch, "transcribe", spy)
    fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ", "--language", "zh"])
    assert captured["languages"][0] == "zh-CN"


def test_unexpected_exception_prints_json_and_exits_1(monkeypatch, capsys) -> None:
    def boom(video_url, *, languages, allow_whisper):
        raise ValueError("surprise")

    monkeypatch.setattr(fetch, "transcribe", boom)
    rc = fetch.main(["transcript", "--video-url", "dQw4w9WgXcQ"])
    assert rc == 1
    payload = _out_json(capsys)
    assert payload["error"] == "unexpected"
    assert "ValueError" in payload["detail"]
