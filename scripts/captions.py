"""Stage: native YouTube caption tracks (free, fast).

`languages=None` means auto mode: prefer the video's own manually-created
track, else the first auto-generated one. An explicit list is walked
left-to-right by youtube-transcript-api; the bare code "zh" expands to the
full Chinese family since YouTube labels Chinese tracks inconsistently.
"""
from __future__ import annotations

from typing import Any

from core import Snippet, TranscriptError
from net import is_block_error, proxy_url, retry_with_backoff

# Order matters: simplified mainland first, then generic, then traditional.
CHINESE_LANG_PREFERENCE: list[str] = [
    "zh-CN",
    "zh-Hans",
    "zh",
    "zh-Hant",
    "zh-TW",
    "zh-HK",
]


def expand_language_preference(codes: list[str] | None) -> list[str] | None:
    """Normalize a user-supplied language list. None/empty -> None (auto)."""
    if not codes:
        return None
    expanded: list[str] = []
    for code in codes:
        if code == "zh":
            expanded.extend(CHINESE_LANG_PREFERENCE)
        else:
            expanded.append(code)
    seen: set[str] = set()
    result: list[str] = []
    for code in expanded:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def select_auto_track(tracks: list) -> Any | None:
    """Pick the best track when no language was requested."""
    if not tracks:
        return None
    manual = [t for t in tracks if not t.is_generated]
    return manual[0] if manual else tracks[0]


def try_captions(
    video_id: str, languages: list[str] | None
) -> tuple[str, list[Snippet]] | None:
    """Return (language_code, snippets) from YouTube captions, or None.

    None means no usable track — the caller falls through to Whisper.
    Raises TranscriptError on hard failures (video gone, network).
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    px = proxy_url()
    if px:
        from youtube_transcript_api.proxies import GenericProxyConfig

        api = YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(http_url=px, https_url=px)
        )
    else:
        api = YouTubeTranscriptApi()

    def _fetch():
        if languages:
            return api.fetch(video_id, languages=languages)
        track = select_auto_track(list(api.list(video_id)))
        return None if track is None else track.fetch()

    def _retryable(exc: BaseException) -> bool:
        if isinstance(exc, (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable)):
            return False
        # Retrying a block from the same IP only extends it; with a (rotating)
        # proxy a retry may land on a fresh exit IP.
        return bool(px) or not is_block_error(exc)

    try:
        fetched = retry_with_backoff(_fetch, attempts=3, should_retry=_retryable)
        if fetched is None:
            return None
    except (NoTranscriptFound, TranscriptsDisabled):
        return None
    except VideoUnavailable as exc:
        raise TranscriptError(
            kind="video_unavailable",
            detail=f"YouTube reports the video is unavailable: {exc}",
            exit_code=2,
        ) from exc
    except Exception as exc:  # network blips, upstream parsing changes
        raise TranscriptError(
            kind="ip_blocked" if is_block_error(exc) else "captions_fetch_failed",
            detail=f"{type(exc).__name__}: {exc}",
            exit_code=1,
        ) from exc

    snippets: list[Snippet] = [
        Snippet(text=s.text, start=float(s.start), duration=float(s.duration))
        for s in fetched
        if (s.text or "").strip()
    ]
    if not snippets:
        return None  # empty track — treat as "no captions"

    return fetched.language_code, snippets
