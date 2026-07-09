"""Whisper speech-to-text fallback for caption-less videos (~$0.006/min)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core import Snippet, TranscriptError

if TYPE_CHECKING:  # pragma: no cover
    from pytubefix import YouTube

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #

# OpenAI Whisper API caps uploads at 25 MB. Target a comfortable margin below.
WHISPER_MAX_BYTES = 25 * 1024 * 1024
WHISPER_TARGET_BYTES = 24 * 1024 * 1024

# Whisper internally downsamples to 16 kHz mono — anything above ~32 kbps is
# wasted bytes. 64 kbps gives headroom for poorly-encoded sources.
AUDIO_BITRATE_KBPS = 64

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_WHISPER_MODEL = "whisper-1"
OPENAI_REQUEST_TIMEOUT_S = 600  # long videos can take a few minutes
OPENAI_MAX_RETRIES = 1

# Whisper's verbose_json returns `language` as a friendly English string
# ("chinese", "english", "japanese", ...). Normalize to ISO-639-1 codes so
# our output matches transcriptapi.com's `language` field shape.
WHISPER_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "chinese": "zh",
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "cantonese": "zh-HK",
    "mandarin": "zh",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "arabic": "ar",
    "hindi": "hi",
    "indonesian": "id",
    "thai": "th",
    "vietnamese": "vi",
    "malay": "ms",
}


def _normalize_whisper_language(value: str | None) -> str:
    """Map Whisper's friendly language name to an ISO-style code."""
    if not value:
        return "unknown"
    return WHISPER_LANGUAGE_NAME_TO_CODE.get(
        value.strip().lower(), value.strip().lower()
    )


def _whisper_request_data(language_hint: str | None) -> dict[str, str]:
    """Form fields for the OpenAI transcriptions call. Hint omitted -> auto-detect."""
    data = {"model": OPENAI_WHISPER_MODEL, "response_format": "verbose_json"}
    if language_hint:
        data["language"] = language_hint
    return data


# --------------------------------------------------------------------------- #
# Stage 2 — Whisper STT                                                       #
# --------------------------------------------------------------------------- #


def download_audio(yt: YouTube, workdir: Path) -> Path:  # pragma: no cover
    """Download the smallest-but-still-usable audio stream via pytubefix.

    Whisper accepts webm/opus directly, so we don't transcode here. The
    Whisper 25 MB cap is enforced separately in `_ensure_whisper_size`.
    """
    from pytubefix.exceptions import PytubeFixError

    streams = yt.streams.filter(only_audio=True).order_by("abr").desc()
    stream = streams.first()
    if stream is None:
        raise TranscriptError(
            kind="audio_download_failed",
            detail="No audio-only streams available for this video.",
            exit_code=1,
        )

    # pytubefix uses subtype "webm"/"mp4" etc. Keep the original container —
    # both webm/opus and m4a/aac are valid Whisper inputs.
    extension = stream.subtype or "webm"
    filename = f"audio.{extension}"
    try:
        stream.download(output_path=str(workdir), filename=filename)
    except PytubeFixError as exc:
        raise TranscriptError(
            kind="audio_download_failed",
            detail=f"pytubefix download failed: {exc}",
            exit_code=1,
        ) from exc

    audio_path = workdir / filename
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise TranscriptError(
            kind="audio_download_failed",
            detail="pytubefix returned without producing an audio file.",
            exit_code=1,
        )
    return audio_path


def _ensure_whisper_size(audio_path: Path, workdir: Path) -> list[Path]:  # pragma: no cover
    """Return one or more files each <= WHISPER_MAX_BYTES, ready for upload.

    Strategy: if the original already fits, use it as-is. Otherwise, transcode
    to a low-bitrate mp3 (Whisper downsamples to 16 kHz mono internally; we
    match that to maximise the minutes-per-MB ratio). If even that exceeds the
    cap (videos longer than ~100 min), segment with ffmpeg.
    """
    if audio_path.stat().st_size <= WHISPER_MAX_BYTES:
        return [audio_path]

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise TranscriptError(
            kind="audio_too_large",
            detail=(
                f"Audio is {audio_path.stat().st_size} bytes (>25 MB) and "
                "ffmpeg/ffprobe is unavailable for re-encode/split."
            ),
            exit_code=1,
        )

    # Step 1: re-encode to 16 kHz mono mp3 at our target bitrate.
    transcoded = workdir / "audio_lo.mp3"
    transcode = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            f"{AUDIO_BITRATE_KBPS}k",
            str(transcoded),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if transcode.returncode != 0 or not transcoded.exists():
        raise TranscriptError(
            kind="audio_transcode_failed",
            detail=f"ffmpeg transcode failed: {transcode.stderr}",
            exit_code=1,
        )

    if transcoded.stat().st_size <= WHISPER_MAX_BYTES:
        return [transcoded]

    # Step 2: segment the transcoded file into <=24 MB chunks.
    return _segment_audio(transcoded, workdir)


def _segment_audio(audio_path: Path, workdir: Path) -> list[Path]:  # pragma: no cover
    """Split an audio file into <=WHISPER_TARGET_BYTES chunks using ffmpeg."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        duration_s = float(probe.stdout.strip())
    except (ValueError, AttributeError) as exc:
        raise TranscriptError(
            kind="audio_probe_failed",
            detail=f"ffprobe duration parse failed: {probe.stderr}",
            exit_code=1,
        ) from exc

    bytes_per_second = audio_path.stat().st_size / max(duration_s, 1.0)
    chunk_seconds = max(60.0, (WHISPER_TARGET_BYTES * 0.92) / bytes_per_second)

    chunks_dir = workdir / "chunks"
    chunks_dir.mkdir(exist_ok=True)
    pattern = str(chunks_dir / "chunk_%03d.mp3")
    split = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(audio_path),
            "-f",
            "segment",
            "-segment_time",
            f"{chunk_seconds:.0f}",
            "-c",
            "copy",
            pattern,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if split.returncode != 0:
        raise TranscriptError(
            kind="audio_split_failed",
            detail=f"ffmpeg split failed: {split.stderr}",
            exit_code=1,
        )

    chunks = sorted(chunks_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise TranscriptError(
            kind="audio_split_failed",
            detail="ffmpeg split produced no chunks.",
            exit_code=1,
        )
    for chunk in chunks:
        if chunk.stat().st_size > WHISPER_MAX_BYTES:
            raise TranscriptError(
                kind="audio_too_large",
                detail=f"Chunk {chunk.name} still exceeds 25 MB after split.",
                exit_code=1,
            )
    return chunks


def _post_whisper(
    audio_path: Path, api_key: str, language_hint: str | None
) -> dict[str, Any]:  # pragma: no cover
    """POST one audio file to OpenAI's transcriptions endpoint."""
    import requests

    for attempt in range(OPENAI_MAX_RETRIES + 1):
        with audio_path.open("rb") as fh:
            try:
                resp = requests.post(
                    OPENAI_TRANSCRIPTIONS_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (audio_path.name, fh, "audio/mpeg")},
                    data=_whisper_request_data(language_hint),
                    timeout=OPENAI_REQUEST_TIMEOUT_S,
                )
            except requests.RequestException as exc:
                if attempt < OPENAI_MAX_RETRIES:
                    continue
                raise TranscriptError(
                    kind="openai_unavailable",
                    detail=f"Network error calling OpenAI: {exc}",
                    exit_code=1,
                ) from exc

        if resp.status_code == 401:
            raise TranscriptError(
                kind="openai_auth",
                detail="OpenAI rejected the API key (401).",
                exit_code=3,
            )
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            if attempt < OPENAI_MAX_RETRIES:
                continue
            raise TranscriptError(
                kind="openai_unavailable",
                detail=f"OpenAI returned {resp.status_code}: {resp.text[:300]}",
                exit_code=1,
            )
        if not resp.ok:
            raise TranscriptError(
                kind="openai_error",
                detail=f"OpenAI {resp.status_code}: {resp.text[:300]}",
                exit_code=1,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise TranscriptError(
                kind="openai_bad_response",
                detail=f"Could not parse OpenAI JSON: {exc}",
                exit_code=1,
            ) from exc

    raise TranscriptError(
        kind="openai_unavailable", detail="Exhausted retries.", exit_code=1
    )


def _whisper_snippets(payload: dict[str, Any], time_offset: float) -> list[Snippet]:
    """Map Whisper verbose_json `segments` into our Snippet shape."""
    segments = payload.get("segments") or []
    snippets: list[Snippet] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw_start = float(seg.get("start", 0.0))
        start = raw_start + time_offset
        end = float(seg.get("end", raw_start)) + time_offset
        snippets.append(Snippet(text=text, start=start, duration=max(0.0, end - start)))
    return snippets


def whisper_transcribe(
    audio_path: Path, api_key: str, workdir: Path, language_hint: str | None
) -> tuple[str, list[Snippet]]:  # pragma: no cover
    """Run Whisper on (possibly chunked) audio. Returns (language, snippets)."""
    chunks = _ensure_whisper_size(audio_path, workdir)
    all_snippets: list[Snippet] = []
    language = language_hint or ""
    offset = 0.0
    for chunk in chunks:
        payload = _post_whisper(chunk, api_key, language_hint)
        all_snippets.extend(_whisper_snippets(payload, offset))
        language = payload.get("language") or language
        offset += float(payload.get("duration") or 0.0)
    return _normalize_whisper_language(language), all_snippets
