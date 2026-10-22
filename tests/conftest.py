"""Make scripts/ importable from tests without packaging."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest


@pytest.fixture(autouse=True)
def _isolate_skipped_log(tmp_path, monkeypatch):
    monkeypatch.setenv("FYY_SKIPPED_LOG", str(tmp_path / "skipped.jsonl"))
    for key in ("YT_PROXY", "HTTPS_PROXY", "https_proxy", "YT_COOKIES_FILE",
                "YT_COOKIES_BROWSER", "TRANSCRIPT_API_KEY", "TRANSCRIPTAPI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
