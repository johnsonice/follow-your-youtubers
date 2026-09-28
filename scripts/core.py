"""Shared types, env loading, and YouTube metadata for follow-your-youtubers."""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from pytubefix import YouTube

# Silence the harmless urllib3/LibreSSL warning on macOS system Python 3.9.
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

# Fallback locations searched for OPENAI_API_KEY when the env var isn't set.
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DOTENV_SEARCH_PATHS: list[Path] = [
    SKILL_DIR / ".env",  # skill-local, gitignored
]


# --------------------------------------------------------------------------- #
# Result types                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Snippet:
    """One transcript segment in the shape transcriptapi.com uses."""

    text: str
    start: float
    duration: float

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": self.start, "duration": self.duration}


@dataclass(frozen=True)
class TranscriptResult:
    video_id: str
    language: str
    snippets: tuple[Snippet, ...]
    metadata: dict[str, Any]
    source: str  # "captions" | "whisper"

    def as_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "language": self.language,
            "transcript": [s.as_dict() for s in self.snippets],
            "metadata": self.metadata,
            "source": self.source,
        }


class TranscriptError(Exception):
    """Expected failure modes. Map to non-zero exit codes."""

    def __init__(self, kind: str, detail: str, *, exit_code: int = 1):
        super().__init__(detail)
        self.kind = kind
        self.exit_code = exit_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# Env / args                                                                  #
# --------------------------------------------------------------------------- #


def load_dotenv_into_env() -> None:
    """Populate os.environ from a discovered .env file. Existing env wins."""
    for path in DOTENV_SEARCH_PATHS:
        if not path.is_file():
            continue
        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
        except OSError:
            # Unreadable file is not fatal — we'll error later if the key is
            # actually needed.
            continue


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:v=|/v/|/embed/|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})"),
]


def extract_video_id(raw: str) -> str:
    """Accept a YouTube URL or a bare 11-char video ID."""
    raw = raw.strip()
    if VIDEO_ID_RE.match(raw):
        return raw
    for pattern in _URL_PATTERNS:
        m = pattern.search(raw)
        if m:
            return m.group(1)
    raise TranscriptError(
        kind="bad_video_url",
        detail=f"Could not extract a YouTube video ID from {raw!r}.",
        exit_code=3,
    )


# --------------------------------------------------------------------------- #
# Metadata + audio (pytubefix)                                                #
# --------------------------------------------------------------------------- #
#
# We use `pytubefix` rather than `yt-dlp` because, as of the time this skill
# was written, YouTube's SABR experiment + PO-token gate blocks `yt-dlp`'s
# default clients on this account without an extra `bgutil-ytdlp-pot-provider`
# Node companion. `pytubefix` reaches YouTube via a different path and works
# out of the box. We still rely on `ffmpeg` for the (rare) re-encode / split
# step when audio exceeds Whisper's 25 MB cap.


def yt_object(video_id: str) -> YouTube:  # pragma: no cover
    """Construct a pytubefix YouTube object for the given video ID.

    Returned so callers can reuse it for both metadata and audio download
    without paying the network round-trip twice.
    """
    from pytubefix import YouTube
    from pytubefix.exceptions import (
        AgeRestrictedError,
        MembersOnly,
        PytubeFixError,
        VideoPrivate,
        VideoUnavailable,
    )

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        return YouTube(url)
    except (VideoPrivate, MembersOnly, AgeRestrictedError, VideoUnavailable) as exc:
        raise TranscriptError(
            kind="video_unavailable",
            detail=f"pytubefix reports the video is unavailable: {exc}",
            exit_code=2,
        ) from exc
    except PytubeFixError as exc:
        raise TranscriptError(
            kind="metadata_fetch_failed",
            detail=f"{type(exc).__name__}: {exc}",
            exit_code=1,
        ) from exc


def fetch_metadata(yt: YouTube) -> dict[str, Any]:  # pragma: no cover
    """Pull title/author/duration off a pytubefix YouTube object.

    Pytubefix lazily fetches the watch page on first attribute access, so any
    failure surfaces here. We map its exceptions into the same TranscriptError
    shapes used elsewhere.
    """
    from pytubefix.exceptions import PytubeFixError

    try:
        return {
            "title": yt.title,
            "author_name": yt.author,
            "author_url": yt.channel_url,
            "duration": yt.length,
        }
    except PytubeFixError as exc:
        raise TranscriptError(
            kind="metadata_fetch_failed",
            detail=f"{type(exc).__name__}: {exc}",
            exit_code=1,
        ) from exc
