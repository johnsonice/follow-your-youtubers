#!/usr/bin/env python3
"""follow-your-youtubers fetch tool.

Subcommands:
  latest      List a channel's recent uploads via YouTube's public RSS feed.
              Free, no API key, any-language channel. Shorts are dropped
              unless --include-shorts is passed.
  transcript  Fetch a video transcript. Order: yt-dlp with browser cookies
              (if YT_COOKIES_FILE / YT_COOKIES_BROWSER is set), native
              captions, yt-dlp without cookies, OpenAI Whisper (~$0.006/min,
              needs OPENAI_API_KEY), then transcriptapi.com as a last resort
              (1 credit, needs TRANSCRIPT_API_KEY).

Output: one JSON object on stdout (transcript also supports --format text).
The transcript shape mirrors transcriptapi.com's /transcript response plus a
`source` field ("captions" | "whisper" | "transcriptapi"). A transcriptapi
result carries `metadata.youtube_error`, the YouTube failure that forced it.

Exit codes:
  0 success · 1 transient (retry once) · 2 video/channel unavailable ·
  3 caller error (bad args, missing OPENAI_API_KEY when Whisper is required).
Every non-zero exit prints {"error": "<kind>", "detail": "<msg>"} on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

from captions import expand_language_preference, try_captions
from core import (
    TranscriptError,
    TranscriptResult,
    extract_video_id,
    fetch_metadata,
    load_dotenv_into_env,
    yt_object,
)
from net import log_skipped, ytdlp_cookie_args
from rss import channel_latest
from transcriptapi import fetch_transcript, transcriptapi_key
from ytdlp_subs import try_ytdlp_subs
from whisper_stt import download_audio, whisper_transcribe


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep the JSON-on-stdout error contract even for bad arguments."""

    def error(self, message: str) -> NoReturn:
        json.dump({"error": "bad_args", "detail": message}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        raise SystemExit(3)


def transcribe(
    video_url: str,
    *,
    languages: list[str] | None,
    allow_whisper: bool,
    transcriptapi_only: bool = False,
    allow_transcriptapi: bool = True,
) -> TranscriptResult:
    """YouTube paths first, transcriptapi last. languages=None means auto-select."""
    video_id = extract_video_id(video_url)
    if transcriptapi_only:
        return transcriptapi_fallback(video_id, TranscriptError(
            kind="youtube_skipped", detail="--transcriptapi-only: YouTube paths not tried."))
    cookie_args = ytdlp_cookie_args()
    try:
        return transcribe_youtube(
            video_id, languages=languages, allow_whisper=allow_whisper, cookie_args=cookie_args
        )
    except TranscriptError as err:
        if not allow_transcriptapi:
            raise
        return transcriptapi_fallback(video_id, err)


def transcriptapi_fallback(video_id: str, youtube_err: TranscriptError) -> TranscriptResult:
    """Last resort. Re-raises the YouTube error (annotated) when it can't help."""
    api_key = transcriptapi_key()
    if not api_key:
        raise TranscriptError(
            kind=youtube_err.kind,
            detail=f"transcriptapi skipped (TRANSCRIPT_API_KEY not set); {youtube_err.detail}",
            exit_code=youtube_err.exit_code,
        ) from youtube_err
    try:
        lang, snippets, metadata = fetch_transcript(video_id, api_key)
    except TranscriptError as api_err:
        raise TranscriptError(
            kind=youtube_err.kind,
            detail=f"transcriptapi failed ({api_err.kind}: {api_err.detail[:200]}); {youtube_err.detail}",
            exit_code=youtube_err.exit_code,
        ) from api_err
    return TranscriptResult(
        video_id=video_id,
        language=lang,
        snippets=tuple(snippets),
        metadata={**metadata, "youtube_error": f"{youtube_err.kind}: {youtube_err.detail[:300]}"},
        source="transcriptapi",
    )


def transcribe_youtube(
    video_id: str,
    *,
    languages: list[str] | None,
    allow_whisper: bool,
    cookie_args: list[str],
) -> TranscriptResult:
    """Cookies -> captions -> yt-dlp -> Whisper, all against YouTube."""
    # Metadata is nice-to-have: a blocked watch page must not cost us the
    # transcript, so degrade to empty metadata instead of aborting.
    yt = None
    try:
        yt = yt_object(video_id)
        metadata = fetch_metadata(yt)
    except TranscriptError as err:
        if err.exit_code == 2:
            raise
        metadata = {"title": None, "author_name": None, "author_url": None,
                    "duration": None, "metadata_error": err.detail[:200]}

    # Stage 0: yt-dlp with cookies. Stage 1: youtube-transcript-api.
    # Stage 2: yt-dlp without cookies.
    captions = None
    primary_err = None
    cookie_err = None
    if cookie_args:
        try:
            captions = try_ytdlp_subs(video_id, languages, cookie_args)
        except TranscriptError as err:
            cookie_err = err
    if captions is None:
        try:
            captions = try_captions(video_id, languages)
        except TranscriptError as err:
            if err.exit_code == 2:
                raise
            primary_err = err
    if captions is None:
        try:
            captions = try_ytdlp_subs(video_id, languages)
        except TranscriptError as err:
            if primary_err is None:
                primary_err = err
    # The cookie-less error is reported first: it is the one that shows an
    # IP block, which the skill's circuit breaker keys on.
    primary_err = primary_err or cookie_err
    if captions is None and primary_err is not None:
        raise primary_err
    if captions is not None:
        lang, snippets = captions
        return TranscriptResult(
            video_id=video_id,
            language=lang,
            snippets=tuple(snippets),
            metadata=metadata,
            source="captions",
        )

    if yt is None:
        raise TranscriptError(
            kind="metadata_fetch_failed",
            detail="No captions and pytubefix could not load the video for Whisper: "
                   + str(metadata.get("metadata_error")),
        )

    if not allow_whisper:
        raise TranscriptError(
            kind="no_captions",
            detail="No caption track found and --no-whisper was set.",
            exit_code=2,
        )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptError(
            kind="missing_openai_key",
            detail=(
                "OPENAI_API_KEY is required for the Whisper fallback. "
                "Set it in your shell or a skill-local .env."
            ),
            exit_code=3,
        )

    # Whisper wants a bare ISO-639-1 code; "zh-CN" -> "zh". No languages -> auto.
    language_hint = languages[0].split("-")[0] if languages else None

    with tempfile.TemporaryDirectory(prefix="fyy_") as tmp:
        workdir = Path(tmp)
        audio_path = download_audio(yt, workdir)
        lang, snippets = whisper_transcribe(audio_path, api_key, workdir, language_hint)

    return TranscriptResult(
        video_id=video_id,
        language=lang or (language_hint or "unknown"),
        snippets=tuple(snippets),
        metadata=metadata,
        source="whisper",
    )


def cmd_latest(args: argparse.Namespace) -> int:
    payload = channel_latest(
        args.channel, limit=args.limit, include_shorts=args.include_shorts
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_transcript(args: argparse.Namespace) -> int:
    result = transcribe(
        args.video_url,
        languages=expand_language_preference(args.language),
        allow_whisper=not args.no_whisper,
        transcriptapi_only=args.transcriptapi_only,
        allow_transcriptapi=not args.no_transcriptapi,
    )
    if args.format == "text":
        sys.stdout.write("".join(s.text for s in result.snippets))
        if not sys.stdout.isatty():
            sys.stdout.write("\n")
        return 0
    json.dump(result.as_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(
        description="Channel discovery (RSS) and transcript fetching (captions -> Whisper)."
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    latest = sub.add_parser("latest", help="List recent uploads for a channel (free).")
    latest.add_argument("--channel", required=True, help="Channel handle, e.g. @MorningstarInc.")
    latest.add_argument(
        "--limit", type=int, default=None,
        help="Max results (default: all ~15 entries YouTube's RSS feed carries).",
    )
    latest.add_argument(
        "--include-shorts", action="store_true",
        help="Keep YouTube Shorts (dropped by default; detected from the feed URL).",
    )
    latest.set_defaults(func=cmd_latest)

    transcript = sub.add_parser(
        "transcript", help="Fetch a transcript: captions first, Whisper fallback."
    )
    transcript.add_argument("--video-url", required=True, help="YouTube URL or 11-char video ID.")
    transcript.add_argument(
        "--language", action="append",
        help="Caption language preference; repeatable. 'zh' expands to the "
             "Chinese family. Default: the video's own track.",
    )
    transcript.add_argument(
        "--no-whisper", action="store_true",
        help="Captions-only mode (free; exits 2 if no captions).",
    )
    transcript.add_argument(
        "--transcriptapi-only", action="store_true",
        help="Skip every YouTube path and go straight to transcriptapi.com "
             "(use after YouTube has blocked this IP in the current run).",
    )
    transcript.add_argument(
        "--no-transcriptapi", action="store_true",
        help="Never fall back to transcriptapi.com (channels tagged backend=local).",
    )
    transcript.add_argument("--format", choices=("json", "text"), default="json")
    transcript.set_defaults(func=cmd_transcript)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv_into_env()
    try:
        return args.func(args)
    except TranscriptError as err:
        if getattr(args, "command", None) == "transcript":
            try:
                vid = extract_video_id(args.video_url)
            except Exception:
                vid = args.video_url
            log_skipped(vid, err.kind, err.detail)
        json.dump({"error": err.kind, "detail": err.detail}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return err.exit_code
    except KeyboardInterrupt:
        json.dump(
            {"error": "interrupted", "detail": "User cancelled."},
            sys.stdout, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 1
    except Exception as exc:  # defensive: the JSON contract covers unexpected bugs too
        json.dump(
            {"error": "unexpected", "detail": f"{type(exc).__name__}: {exc}"},
            sys.stdout, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
