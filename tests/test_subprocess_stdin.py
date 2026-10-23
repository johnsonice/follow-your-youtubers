"""Regression: child processes must not read the caller's stdin.

The skill drives fetch.py from a `while read` loop. ffmpeg (Whisper path) and
yt-dlp inherited that stdin, swallowed queued lines, and corrupted the loop:
on 10-16 a RhinoFinance transcript landed in transcripts/@inance/.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LINES = ["@RhinoFinance JlFrJ45B6zU", "@AlanChen IdIH1yo-llA", "@meetkevin abcdefghijk"]

# Each fake tool swallows one line of stdin, as ffmpeg does when it polls for keys.
FAKE_TOOL = """#!/bin/sh
read -r _swallowed
for last; do :; done
case "$0" in *ffmpeg) : > "$last" ;; *ffprobe) echo 60 ;; esac
exit 0
"""

DRIVERS = {
    "ffmpeg": """
        from pathlib import Path
        from whisper_stt import WHISPER_MAX_BYTES, _ensure_whisper_size
        work = Path(sys.argv[1])
        big = work / "audio.m4a"
        with big.open("wb") as fh:
            fh.truncate(WHISPER_MAX_BYTES + 1)
        _ensure_whisper_size(big, work)
    """,
    "yt-dlp": """
        from ytdlp_subs import try_ytdlp_subs
        try_ytdlp_subs("abcdefghijk", ["en"])
    """,
}


@pytest.fixture
def fake_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("ffmpeg", "ffprobe", "yt-dlp"):
        tool = bin_dir / name
        tool.write_text(FAKE_TOOL)
        tool.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize("tool", sorted(DRIVERS))
def test_while_read_loop_keeps_every_line(tool, fake_bin, tmp_path):
    driver = tmp_path / "driver.py"
    driver.write_text(
        f"import sys\nsys.path.insert(0, {str(SCRIPTS)!r})\n" + textwrap.dedent(DRIVERS[tool])
    )
    loop = f'while read -r line; do "{sys.executable}" "{driver}" "{tmp_path}"; echo "saw:$line"; done'

    proc = subprocess.run(
        ["bash", "-c", loop],
        input="\n".join(LINES) + "\n",
        capture_output=True,
        text=True,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=60,
    )

    assert proc.stdout.splitlines() == [f"saw:{line}" for line in LINES], proc.stderr
