"""Network helpers: proxy config, retry/backoff, skipped-video log.

Proxy: set YT_PROXY (preferred) or HTTPS_PROXY / https_proxy, e.g.
  YT_PROXY=http://user:pass@host:port
It is applied to youtube-transcript-api, pytubefix and the yt-dlp fallback.
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

SKILL_DIR = Path(__file__).resolve().parent.parent
SKIPPED_LOG = SKILL_DIR / "transcripts" / "skipped.jsonl"

BLOCK_MARKERS = ("IpBlocked", "RequestBlocked", "429", "Too Many Requests")


def proxy_url() -> Optional[str]:
    for key in ("YT_PROXY", "HTTPS_PROXY", "https_proxy"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def is_block_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(m in text for m in BLOCK_MARKERS)


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    should_retry: Callable[[BaseException], bool] = lambda e: True,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying on exceptions accepted by should_retry.

    Delay doubles each attempt (base, 2*base, ...) plus up to 1s jitter.
    """
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if i == attempts - 1 or not should_retry(exc):
                raise
            sleep(base_delay * (2 ** i) + random.uniform(0, 1))
    raise AssertionError("unreachable")


def log_skipped(video_id: str, kind: str, detail: str, path: Optional[Path] = None) -> None:
    """Append a JSON line so skipped videos can be retried later."""
    target = path or Path(os.environ.get("FYY_SKIPPED_LOG", SKIPPED_LOG))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "video_id": video_id,
                "error": kind,
                "detail": detail[:500],
                "proxy": bool(proxy_url()),
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break the fetch
