from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import fetch
import net
import transcriptapi
import ytdlp_subs
from core import Snippet, TranscriptError

VID = "dQw4w9WgXcQ"
BLOCKED = TranscriptError(kind="captions_fetch_failed", detail="IpBlocked: YouTube is blocking requests")


def test_cookie_args_empty_when_unconfigured():
    assert net.ytdlp_cookie_args() == []


def test_cookie_args_from_browser(monkeypatch):
    monkeypatch.setenv("YT_COOKIES_BROWSER", "chrome:Profile 1")
    assert net.ytdlp_cookie_args() == ["--cookies-from-browser", "chrome:Profile 1"]


def test_cookie_file_wins_over_browser(monkeypatch, tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("YT_COOKIES_BROWSER", "chrome")
    monkeypatch.setenv("YT_COOKIES_FILE", str(cookies))
    assert net.ytdlp_cookie_args() == ["--cookies", str(cookies)]


def test_missing_cookie_file_is_a_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("YT_COOKIES_FILE", str(tmp_path / "nope.txt"))
    with pytest.raises(TranscriptError) as exc:
        net.ytdlp_cookie_args()
    assert (exc.value.kind, exc.value.exit_code) == ("bad_cookies_file", 3)


def test_ytdlp_passes_cookie_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(ytdlp_subs.shutil, "which", lambda name: "/usr/bin/yt-dlp")

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(ytdlp_subs.subprocess, "run", fake_run)
    assert ytdlp_subs.try_ytdlp_subs(VID, ["en"], ["--cookies-from-browser", "chrome"]) is None
    cmd = seen["cmd"]
    assert cmd[cmd.index("--cookies-from-browser") + 1] == "chrome"
    assert cmd[-1] == f"https://www.youtube.com/watch?v={VID}"


@pytest.fixture
def youtube(monkeypatch):
    """Stub every YouTube stage; tests set what each one returns or raises."""
    calls: list[str] = []
    stages = {"cookies": None, "captions": None, "ytdlp": None}

    def outcome(name):
        calls.append(name)
        value = stages[name]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(fetch, "yt_object", lambda vid: object())
    monkeypatch.setattr(fetch, "fetch_metadata", lambda yt: {"title": "T"})
    monkeypatch.setattr(fetch, "try_captions", lambda vid, langs: outcome("captions"))
    monkeypatch.setattr(
        fetch, "try_ytdlp_subs",
        lambda vid, langs, cookie_args=(): outcome("cookies" if cookie_args else "ytdlp"),
    )
    return SimpleNamespace(calls=calls, stages=stages)


def test_cookies_stage_runs_first_and_wins(monkeypatch, youtube):
    monkeypatch.setenv("YT_COOKIES_BROWSER", "chrome")
    youtube.stages["cookies"] = ("en", [Snippet("hi", 0.0, 1.0)])

    result = fetch.transcribe(VID, languages=["en"], allow_whisper=False)

    assert youtube.calls == ["cookies"]
    assert (result.source, result.snippets[0].text) == ("captions", "hi")


def test_without_cookies_the_existing_path_is_unchanged(youtube):
    youtube.stages["captions"] = ("en", [Snippet("hi", 0.0, 1.0)])

    fetch.transcribe(VID, languages=["en"], allow_whisper=False)

    assert youtube.calls == ["captions"]


def test_failed_cookies_fall_through_to_existing_path(monkeypatch, youtube):
    monkeypatch.setenv("YT_COOKIES_BROWSER", "chrome")
    youtube.stages["cookies"] = TranscriptError(kind="ytdlp_failed", detail="Sign in to confirm")
    youtube.stages["captions"] = ("en", [Snippet("hi", 0.0, 1.0)])

    result = fetch.transcribe(VID, languages=["en"], allow_whisper=False)

    assert youtube.calls == ["cookies", "captions"]
    assert result.source == "captions"


def test_no_api_key_reraises_youtube_error_and_logs_skip(youtube, capsys, tmp_path):
    youtube.stages["captions"] = BLOCKED

    rc = fetch.main(["transcript", f"--video-url={VID}", "--no-whisper"])

    assert rc == 1
    assert json.loads(capsys.readouterr().out)["error"] == "captions_fetch_failed"
    row = json.loads((tmp_path / "skipped.jsonl").read_text().splitlines()[0])
    assert row["video_id"] == VID
    assert row["error"] == "captions_fetch_failed"
    assert row["detail"].startswith("transcriptapi skipped (TRANSCRIPT_API_KEY not set); IpBlocked")


def test_api_runs_only_after_youtube_fails(monkeypatch, youtube):
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_test")
    youtube.stages["captions"] = BLOCKED
    api_calls = []

    def fake_api(vid, key):
        api_calls.append((vid, key))
        return "en", [Snippet("from api", 0.0, 2.0)], {"title": "T"}

    monkeypatch.setattr(fetch, "fetch_transcript", fake_api)

    result = fetch.transcribe(VID, languages=["en"], allow_whisper=False)

    assert youtube.calls == ["captions", "ytdlp"]
    assert api_calls == [(VID, "sk_test")]
    assert result.source == "transcriptapi"
    assert result.metadata["youtube_error"].startswith("captions_fetch_failed: IpBlocked")


def test_api_not_called_when_youtube_succeeds(monkeypatch, youtube):
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_test")
    youtube.stages["captions"] = ("en", [Snippet("hi", 0.0, 1.0)])
    monkeypatch.setattr(fetch, "fetch_transcript", lambda *a: pytest.fail("API must not be called"))

    assert fetch.transcribe(VID, languages=["en"], allow_whisper=False).source == "captions"


def test_api_failure_keeps_youtube_error_kind(monkeypatch, youtube):
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_test")
    youtube.stages["captions"] = BLOCKED

    def no_credits(vid, key):
        raise TranscriptError(kind="transcriptapi_no_credits", detail="HTTP 402", exit_code=3)

    monkeypatch.setattr(fetch, "fetch_transcript", no_credits)

    with pytest.raises(TranscriptError) as exc:
        fetch.transcribe(VID, languages=["en"], allow_whisper=False)
    assert exc.value.kind == "captions_fetch_failed"
    assert exc.value.detail.startswith("transcriptapi failed (transcriptapi_no_credits: HTTP 402); IpBlocked")


def test_transcriptapi_only_skips_youtube(monkeypatch, youtube):
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_test")
    monkeypatch.setattr(fetch, "fetch_transcript", lambda vid, key: ("en", [Snippet("x", 0.0, 1.0)], {}))

    result = fetch.transcribe(VID, languages=["en"], allow_whisper=True, transcriptapi_only=True)

    assert youtube.calls == []
    assert result.metadata["youtube_error"] == "youtube_skipped: --transcriptapi-only: YouTube paths not tried."


def test_transcriptapi_key_precedence(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTAPI_API_KEY", "sk_old")
    assert transcriptapi.transcriptapi_key() == "sk_old"
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_new")
    assert transcriptapi.transcriptapi_key() == "sk_new"


def _response(status, body):
    return SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body)


def test_fetch_transcript_sends_auth_and_parses_rows():
    seen = {}

    def get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return _response(200, {
            "video_id": VID, "language": "zh",
            "transcript": [{"text": "你好", "start": 1, "duration": 2}, {"text": " ", "start": 3, "duration": 1}],
            "metadata": {"title": "T"},
        })

    lang, snippets, metadata = transcriptapi.fetch_transcript(VID, "sk_test", get=get)

    assert (lang, snippets, metadata) == ("zh", [Snippet("你好", 1.0, 2.0)], {"title": "T"})
    assert seen["url"] == "https://transcriptapi.com/api/v2/youtube/transcript"
    assert seen["params"]["video_url"] == VID
    assert seen["headers"] == {"Authorization": "Bearer sk_test", "User-Agent": "follow-your-youtubers/1.0"}


@pytest.mark.parametrize("status,kind,code", [
    (402, "transcriptapi_no_credits", 3),
    (404, "transcriptapi_not_found", 2),
    (429, "transcriptapi_rate_limited", 1),
    (500, "transcriptapi_failed", 1),
])
def test_fetch_transcript_maps_http_errors(status, kind, code):
    with pytest.raises(TranscriptError) as exc:
        transcriptapi.fetch_transcript(VID, "sk_test", get=lambda *a, **k: _response(status, {"detail": "x"}))
    assert (exc.value.kind, exc.value.exit_code) == (kind, code)


def test_no_transcriptapi_flag_keeps_the_plain_youtube_error(monkeypatch, youtube):
    monkeypatch.setenv("TRANSCRIPT_API_KEY", "sk_test")
    youtube.stages["captions"] = BLOCKED
    monkeypatch.setattr(fetch, "fetch_transcript", lambda *a: pytest.fail("API must not be called"))

    with pytest.raises(TranscriptError) as exc:
        fetch.transcribe(VID, languages=["en"], allow_whisper=False, allow_transcriptapi=False)
    assert exc.value.detail == BLOCKED.detail


def test_ip_block_is_reported_over_a_cookie_failure(monkeypatch, youtube):
    monkeypatch.setenv("YT_COOKIES_BROWSER", "chrome")
    youtube.stages["cookies"] = TranscriptError(kind="ytdlp_failed", detail="Sign in to confirm")
    youtube.stages["captions"] = BLOCKED

    with pytest.raises(TranscriptError) as exc:
        fetch.transcribe(VID, languages=["en"], allow_whisper=False)
    assert "IpBlocked" in exc.value.detail
