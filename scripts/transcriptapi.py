"""Last-resort stage: the transcriptapi.com HTTP API (1 credit per transcript).

Only reached after every YouTube path (cookies, direct, proxy, Whisper) has
failed, because it costs money and does not touch this machine's IP.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from core import Snippet, TranscriptError

API_URL = "https://transcriptapi.com/api/v2/youtube/transcript"
# Cloudflare rejects requests without a real User-Agent (403 / error 1010).
USER_AGENT = "follow-your-youtubers/1.0"
REQUEST_TIMEOUT_S = 60

# HTTP status -> (error kind, exit code). Anything else is transient.
_STATUS_ERRORS: dict[int, tuple[str, int]] = {
    401: ("transcriptapi_auth", 3),
    402: ("transcriptapi_no_credits", 3),
    404: ("transcriptapi_not_found", 2),
    422: ("transcriptapi_bad_request", 3),
    429: ("transcriptapi_rate_limited", 1),
}


def transcriptapi_key() -> Optional[str]:
    for key in ("TRANSCRIPT_API_KEY", "TRANSCRIPTAPI_API_KEY"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def parse_response(data: dict[str, Any]) -> tuple[str, list[Snippet], dict[str, Any]]:
    snippets = [
        Snippet(text=row["text"], start=float(row["start"]), duration=float(row["duration"]))
        for row in data.get("transcript") or []
        if row.get("text", "").strip()
    ]
    if not snippets:
        raise TranscriptError(
            kind="transcriptapi_empty", detail="transcriptapi returned no transcript rows.", exit_code=2
        )
    return data.get("language") or "unknown", snippets, data.get("metadata") or {}


def fetch_transcript(
    video_id: str, api_key: str, *, get: Optional[Callable[..., Any]] = None
) -> tuple[str, list[Snippet], dict[str, Any]]:
    if get is None:  # pragma: no cover
        import requests

        get = requests.get
    try:
        resp = get(
            API_URL,
            params={"video_url": video_id, "format": "json", "send_metadata": "true"},
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_S,
        )
    except Exception as exc:
        raise TranscriptError(kind="transcriptapi_unavailable", detail=f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code != 200:
        kind, code = _STATUS_ERRORS.get(resp.status_code, ("transcriptapi_failed", 1))
        raise TranscriptError(kind=kind, detail=f"HTTP {resp.status_code}: {resp.text[:300]}", exit_code=code)
    return parse_response(resp.json())
