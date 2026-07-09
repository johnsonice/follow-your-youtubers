"""Unit tests for scripts/captions.py — pure logic only, no network."""
from __future__ import annotations

from dataclasses import dataclass

from captions import (
    CHINESE_LANG_PREFERENCE,
    expand_language_preference,
    select_auto_track,
)


def test_none_means_auto() -> None:
    assert expand_language_preference(None) is None


def test_empty_means_auto() -> None:
    assert expand_language_preference([]) is None


def test_zh_expands_to_chinese_family() -> None:
    assert expand_language_preference(["zh"]) == CHINESE_LANG_PREFERENCE


def test_other_codes_pass_through_in_order() -> None:
    assert expand_language_preference(["ja", "en"]) == ["ja", "en"]


def test_expansion_dedupes_preserving_order() -> None:
    result = expand_language_preference(["zh-CN", "zh"])
    assert result[0] == "zh-CN"
    assert result.count("zh-CN") == 1
    assert set(CHINESE_LANG_PREFERENCE).issubset(set(result))


@dataclass(frozen=True)
class _FakeTrack:
    language_code: str
    is_generated: bool


def test_select_auto_track_prefers_manual() -> None:
    tracks = [
        _FakeTrack(language_code="en", is_generated=True),
        _FakeTrack(language_code="ja", is_generated=False),
    ]
    assert select_auto_track(tracks).language_code == "ja"


def test_select_auto_track_falls_back_to_first_generated() -> None:
    tracks = [
        _FakeTrack(language_code="en", is_generated=True),
        _FakeTrack(language_code="de", is_generated=True),
    ]
    assert select_auto_track(tracks).language_code == "en"


def test_select_auto_track_empty_returns_none() -> None:
    assert select_auto_track([]) is None
