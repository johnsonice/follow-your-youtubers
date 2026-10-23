"""Fallback stage: subtitles via the yt-dlp CLI (different client/endpoints
than youtube-transcript-api, so it often survives when that one is blocked).

Returns (language, snippets) or None if yt-dlp is missing / no subtitles.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from core import Snippet, TranscriptError
from net import proxy_url


def parse_json3(data: dict) -> list[Snippet]:
    out: list[Snippet] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        if not text.strip():
            continue
        out.append(Snippet(
            text=text,
            start=ev.get("tStartMs", 0) / 1000.0,
            duration=ev.get("dDurationMs", 0) / 1000.0,
        ))
    return out


def try_ytdlp_subs(
    video_id: str,
    languages: Optional[list[str]],
    cookie_args: Sequence[str] = (),
) -> Optional[tuple[str, list[Snippet]]]:
    exe = shutil.which("yt-dlp")
    if not exe:
        return None
    langs = ",".join(languages) if languages else "en.*,zh.*,.*-orig"
    with tempfile.TemporaryDirectory(prefix="fyy_subs_") as tmp:
        cmd = [
            # Subtitles don't need a playable format; without this flag yt-dlp
            # aborts with "Requested format is not available" before writing them.
            exe, "--skip-download", "--ignore-no-formats-error",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", langs, "--sub-format", "json3",
            "-o", str(Path(tmp) / "%(id)s"), "--no-warnings", "--quiet",
        ]
        cmd += list(cookie_args)
        px = proxy_url()
        if px:
            cmd += ["--proxy", px]
        cmd.append(f"https://www.youtube.com/watch?v={video_id}")
        try:
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscriptError(kind="ytdlp_failed", detail="yt-dlp timed out") from exc
        files = sorted(Path(tmp).glob(f"{video_id}.*.json3"))
        if not files:
            if proc.returncode != 0:
                raise TranscriptError(kind="ytdlp_failed", detail=(proc.stderr or "")[-400:])
            return None
        # Prefer the first requested language that was downloaded.
        chosen = files[0]
        if languages:
            for code in languages:
                hit = [f for f in files if f.name.split(".")[-2] == code]
                if hit:
                    chosen = hit[0]
                    break
        lang = chosen.name.split(".")[-2]
        snippets = parse_json3(json.loads(chosen.read_text(encoding="utf-8")))
        return (lang, snippets) if snippets else None
