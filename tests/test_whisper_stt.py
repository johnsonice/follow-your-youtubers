"""Unit tests for scripts/whisper_stt.py — pure logic only, no network."""
from __future__ import annotations

from whisper_stt import (
    _normalize_whisper_language,
    _whisper_request_data,
    _whisper_snippets,
)


def test_normalize_known_language_name() -> None:
    assert _normalize_whisper_language("Chinese") == "zh"
    assert _normalize_whisper_language("english") == "en"


def test_normalize_unknown_lowercases_and_strips() -> None:
    assert _normalize_whisper_language("  Klingon ") == "klingon"


def test_normalize_empty_returns_unknown() -> None:
    assert _normalize_whisper_language(None) == "unknown"
    assert _normalize_whisper_language("") == "unknown"


def test_request_data_includes_hint_when_given() -> None:
    data = _whisper_request_data("zh")
    assert data["language"] == "zh"
    assert data["model"] == "whisper-1"
    assert data["response_format"] == "verbose_json"


def test_request_data_omits_language_when_no_hint() -> None:
    data = _whisper_request_data(None)
    assert "language" not in data
    assert data["model"] == "whisper-1"


def test_whisper_snippets_applies_offset_and_skips_blank() -> None:
    payload = {
        "segments": [
            {"text": " first ", "start": 0.0, "end": 2.0},
            {"text": "   ", "start": 2.0, "end": 3.0},
            {"text": "second", "start": 2.0, "end": 5.0},
        ]
    }
    snippets = _whisper_snippets(payload, 100.0)
    assert [s.text for s in snippets] == ["first", "second"]
    assert [s.start for s in snippets] == [100.0, 102.0]
    assert snippets[1].duration == 3.0


def test_whisper_snippets_empty_payload() -> None:
    assert _whisper_snippets({}, 0.0) == []
