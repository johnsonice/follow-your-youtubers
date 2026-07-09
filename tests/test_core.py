"""Unit tests for scripts/core.py — pure logic only, no network."""
from __future__ import annotations

import os

import pytest

import core
from core import Snippet, TranscriptError, extract_video_id, load_dotenv_into_env


@pytest.mark.parametrize(
    "raw",
    [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "  dQw4w9WgXcQ  ",
    ],
)
def test_extract_video_id_accepts_common_forms(raw: str) -> None:
    assert extract_video_id(raw) == "dQw4w9WgXcQ"


def test_extract_video_id_rejects_garbage_with_exit_3() -> None:
    with pytest.raises(TranscriptError) as exc:
        extract_video_id("not a video url")
    assert exc.value.exit_code == 3
    assert exc.value.kind == "bad_video_url"


def test_snippet_as_dict_roundtrip() -> None:
    snippet = Snippet(text="hello", start=1.5, duration=2.0)
    assert snippet.as_dict() == {"text": "hello", "start": 1.5, "duration": 2.0}


def test_dotenv_existing_env_wins(monkeypatch, tmp_path) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text("OPENAI_API_KEY=sk-from-file\n", encoding="utf-8")
    monkeypatch.setattr(core, "DOTENV_SEARCH_PATHS", [envfile])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    load_dotenv_into_env()
    assert os.environ["OPENAI_API_KEY"] == "sk-from-env"


def test_dotenv_fills_missing_and_strips_quotes(monkeypatch, tmp_path) -> None:
    envfile = tmp_path / ".env"
    envfile.write_text('# comment\n\nOPENAI_API_KEY="sk-from-file"\n', encoding="utf-8")
    monkeypatch.setattr(core, "DOTENV_SEARCH_PATHS", [envfile])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    load_dotenv_into_env()
    assert os.environ["OPENAI_API_KEY"] == "sk-from-file"


def test_dotenv_missing_file_is_silent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "DOTENV_SEARCH_PATHS", [tmp_path / "absent.env"])
    load_dotenv_into_env()  # must not raise
