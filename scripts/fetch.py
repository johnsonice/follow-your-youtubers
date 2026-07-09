#!/usr/bin/env python3
"""follow-your-youtubers fetch tool.

Subcommands:
  latest      List a channel's recent uploads via YouTube's public RSS feed.
              Free, no API key, any-language channel.
  transcript  Fetch a video transcript: native captions first (free), then
              OpenAI Whisper fallback (~$0.006/min, needs OPENAI_API_KEY).

Output: one JSON object on stdout (transcript also supports --format text).
The transcript shape mirrors transcriptapi.com's /transcript response plus a
`source` field ("captions" | "whisper").

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
from rss import channel_latest
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
) -> TranscriptResult:
    """Captions -> Whisper orchestration. languages=None means auto-select."""
    video_id = extract_video_id(video_url)
    yt = yt_object(video_id)
    metadata = fetch_metadata(yt)

    captions = try_captions(video_id, languages)
    if captions is not None:
        lang, snippets = captions
        return TranscriptResult(
            video_id=video_id,
            language=lang,
            snippets=tuple(snippets),
            metadata=metadata,
            source="captions",
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
    payload = channel_latest(args.channel, limit=args.limit)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_transcript(args: argparse.Namespace) -> int:
    result = transcribe(
        args.video_url,
        languages=expand_language_preference(args.language),
        allow_whisper=not args.no_whisper,
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
    transcript.add_argument("--format", choices=("json", "text"), default="json")
    transcript.set_defaults(func=cmd_transcript)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv_into_env()
    try:
        return args.func(args)
    except TranscriptError as err:
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
