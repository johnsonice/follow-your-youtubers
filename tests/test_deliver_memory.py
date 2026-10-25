from __future__ import annotations

import json
from pathlib import Path

import deliver_memory as dm

TRANSCRIPT = """---
title: "PREPARE: The Bailout is Coming."
channel: "@meetkevin"
published: 2026-10-23
url: https://youtube.com/watch?v=d5sUN3Gx18Q
videoId: d5sUN3Gx18Q
captured: 2026-10-24
language: en
transcript_source: captions
---

Warren Buffett and Berkshire Hathaway are saving Meta.
"""


def write_transcript(root: Path, handle: str, name: str, text: str) -> Path:
    path = root / handle / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FakeOmem:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, argv):
        body_file = argv[argv.index("--body-file") + 1]
        self.calls.append((argv, Path(body_file).read_text(encoding="utf-8")))
        return self.replies.pop(0)


def test_delivers_each_transcript_as_a_source_with_a_readable_header(tmp_path):
    root = tmp_path / "transcripts"
    write_transcript(root, "@meetkevin", "2026-10-23_d5sUN3Gx18Q.md", TRANSCRIPT)
    omem = FakeOmem([(0, {"status": "captured", "path": "inbox/x"})])

    report = dm.deliver(root, "2026-10-24", "2026-10-24", topic="trading-research",
                        by="follow-your-youtubers@mac", run=omem)

    argv, body = omem.calls[0]
    assert argv == ["capture", "--topic", "trading-research", "--kind", "source",
                    "--source-id", "youtube:d5sUN3Gx18Q",
                    "--summary", "@meetkevin 2026-10-23: PREPARE: The Bailout is Coming.",
                    "--by", "follow-your-youtubers@mac", "--title-hint", "meetkevin d5sUN3Gx18Q",
                    "--body-file", argv[-1]]
    assert body == ("Channel: @meetkevin\nPublished: 2026-10-23\nURL: https://youtube.com/watch?v=d5sUN3Gx18Q\n"
                    "Language: en\n\nWarren Buffett and Berkshire Hathaway are saving Meta.\n")
    assert report == {"captured": 1, "skipped": 0, "errors": []}


def test_only_transcripts_captured_in_range_are_sent(tmp_path):
    root = tmp_path / "transcripts"
    write_transcript(root, "@meetkevin", "a.md", TRANSCRIPT)
    write_transcript(root, "@meetkevin", "b.md", TRANSCRIPT.replace("captured: 2026-10-24", "captured: 2026-10-19")
                     .replace("d5sUN3Gx18Q", "OLDvideo000"))
    omem = FakeOmem([(0, {"status": "captured"})])

    report = dm.deliver(root, "2026-10-20", "2026-10-24", topic="trading-research", by="b", run=omem)

    assert [c[0][c[0].index("--source-id") + 1] for c in omem.calls] == ["youtube:d5sUN3Gx18Q"]
    assert report["captured"] == 1


def test_counts_duplicates_and_rejections_separately(tmp_path):
    root = tmp_path / "transcripts"
    write_transcript(root, "@a", "1.md", TRANSCRIPT)
    write_transcript(root, "@b", "2.md", TRANSCRIPT.replace("d5sUN3Gx18Q", "zSECONDvid0"))
    omem = FakeOmem([(0, {"status": "skipped", "reason": "dup"}),
                     (2, {"error": "blocked: sensitive (IPv4 address). Remove it before writing to memory."})])

    report = dm.deliver(root, "2026-10-24", "2026-10-24", topic="trading-research", by="b", run=omem)

    assert report == {"captured": 0, "skipped": 1,
                      "errors": ["youtube:zSECONDvid0: blocked: sensitive (IPv4 address). Remove it before writing to memory."]}


def test_main_skips_quietly_when_omniverse_memory_is_not_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dm, "find_omem", lambda: None)

    code = dm.main(["--transcripts", str(tmp_path), "--from", "2026-10-24"])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "skipped", "reason": "omniverse-memory is not installed"}
