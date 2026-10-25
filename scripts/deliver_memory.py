#!/usr/bin/env python3
"""Deliver saved transcripts to the owner's omniverse-memory vault.

Each transcript captured in the date range becomes one `omem capture --kind
source` call with source id `youtube:<videoId>`. The vault skips ids it already
holds, so rerunning is safe. Without omniverse-memory installed or configured,
this prints a skip notice and exits 0, so the daily run never fails on it.

Usage: deliver_memory.py --from YYYY-MM-DD [--to YYYY-MM-DD] [--topic trading-research]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable, Optional

SKILL_DIR = Path(__file__).resolve().parent.parent
OMEM_CANDIDATES = (
    Path("~/.claude/skills/omniverse-memory/scripts/omem").expanduser(),
    Path("~/.agents/skills/omniverse-memory/scripts/omem").expanduser(),
)
Runner = Callable[[list], tuple]


def find_omem() -> Optional[Path]:
    override = os.environ.get("OMEM_BIN")
    candidates = [Path(override)] if override else list(OMEM_CANDIDATES)
    return next((p for p in candidates if p.is_file()), None)


def split_front(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"')
    return meta, body.lstrip("\n")


def transcripts_in_range(root: Path, start: str, end: str) -> list[tuple[dict, str]]:
    found = []
    for path in sorted(root.glob("@*/*.md")):
        meta, body = split_front(path.read_text(encoding="utf-8"))
        if meta.get("videoId") and start <= meta.get("captured", "") <= end:
            found.append((meta, body))
    return sorted(found, key=lambda item: (item[0]["captured"], item[0]["channel"], item[0]["videoId"]))


def capture_argv(meta: dict, topic: str, by: str, body_file: str) -> list:
    handle = meta["channel"]
    return ["capture", "--topic", topic, "--kind", "source", "--source-id", f"youtube:{meta['videoId']}",
            "--summary", f"{handle} {meta.get('published', '')}: {meta.get('title', '')}",
            "--by", by, "--title-hint", f"{handle.lstrip('@')} {meta['videoId']}", "--body-file", body_file]


def deliver(root: Path, start: str, end: str, *, topic: str, by: str, run: Runner) -> dict:
    report = {"captured": 0, "skipped": 0, "errors": []}
    for meta, body in transcripts_in_range(root, start, end):
        header = (f"Channel: {meta['channel']}\nPublished: {meta.get('published', '')}\n"
                  f"URL: {meta.get('url', '')}\nLanguage: {meta.get('language', '')}\n\n")
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8", delete=False) as fh:
            fh.write(header + body)
        try:
            code, result = run(capture_argv(meta, topic, by, fh.name))
        finally:
            os.unlink(fh.name)
        status = result.get("status")
        if code == 0 and status in ("captured", "skipped"):
            report[status] += 1
        else:
            report["errors"].append(f"youtube:{meta['videoId']}: {result.get('error', result)}")
    return report


def omem_runner(omem: Path) -> Runner:
    def run(argv: list) -> tuple:
        # stdin is closed so omem never eats lines from a calling `while read` loop.
        proc = subprocess.run([str(omem), *argv], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        try:
            return proc.returncode, json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.returncode, {"error": (proc.stdout + proc.stderr).strip()[-300:]}
    return run


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transcripts", type=Path, default=SKILL_DIR / "transcripts")
    parser.add_argument("--from", dest="start", default=date.today().isoformat())
    parser.add_argument("--to", dest="end")
    parser.add_argument("--topic", default="trading-research")
    args = parser.parse_args(argv)
    omem = find_omem()
    if omem is None:
        print(json.dumps({"status": "skipped", "reason": "omniverse-memory is not installed"}))
        return 0
    run = omem_runner(omem)
    code, config = run(["config"])
    if code != 0:
        print(json.dumps({"status": "skipped", "reason": config.get("error", "omniverse-memory is not configured")}))
        return 0
    report = deliver(args.transcripts, args.start, args.end or args.start, topic=args.topic,
                     by=f"follow-your-youtubers@{socket.gethostname().split('.')[0]}", run=run)
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
