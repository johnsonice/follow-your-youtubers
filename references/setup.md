# Setup

First-run requirements for follow-your-youtubers.

## Prerequisites

- **Python** 3.9 or newer (macOS system Python is fine).
- **ffmpeg** + **ffprobe** on `PATH`. Only used when the downloaded audio is
  larger than Whisper's 25 MB API limit (videos longer than ~25 min at the
  default ~160 kbps stream). For shorter videos, ffmpeg is never invoked.

```bash
# macOS
brew install ffmpeg

# Linux (Debian/Ubuntu)
sudo apt-get install -y ffmpeg
```

## Install (skill-local venv)

The skill ships with a self-contained virtualenv to avoid polluting the
system Python and to pin dependencies independently of any other tool the
user runs.

```bash
cd ~/.claude/skills/follow-your-youtubers  # or wherever you cloned the repo
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Verify:

```bash
.venv/bin/python -c "import youtube_transcript_api, pytubefix, requests; print('OK')"
```

## OPENAI_API_KEY (Whisper fallback only)

The script discovers the key in this order — first match wins:

1. The inherited shell environment (`export OPENAI_API_KEY=sk-...`).
2. A skill-local `.env` (gitignored) — **the recommended location**:
   `echo 'OPENAI_API_KEY=sk-...' > .env` in the skill directory.

If none of the above is set and the captions path fails, the script exits
with code 3 and `{"error": "missing_openai_key", ...}`. The captions-only
path (`--no-whisper`) works without any key.

## TRANSCRIPTAPI_API_KEY (optional stage-1 backend)

Set `TRANSCRIPTAPI_API_KEY` (same discovery order as above) or install the
`transcriptapi` skill to enable the transcriptapi backend — the most
reliable option, at 1 credit per transcript. Without it, the skill uses the
free local captions path and (if `OPENAI_API_KEY` is set) Whisper.

## Why `pytubefix` instead of `yt-dlp`

YouTube currently runs a "SABR" experiment that forces server-side ad
placement. On accounts where it's enabled (most personal accounts as of
the time this skill was written), `yt-dlp`'s default `web` and `tv` clients
get HTTP 403 on the actual audio stream URLs, even with valid cookies.

The standard workaround for `yt-dlp` is to install the
[`bgutil-ytdlp-pot-provider`](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
plugin, which uses a Node.js companion to generate PO tokens. That works,
but it's an extra moving piece: a Python plugin + an npm/yarn-built Node
project that has to be kept in sync with the plugin version.

`pytubefix` reaches YouTube through a different code path and downloads
audio without the PO-token gate. It does not need Node, does not need
cookies, and works straight after `pip install pytubefix`. If `pytubefix`
ever breaks because YouTube changes its mobile-client endpoints, the fix
is typically just `pip install -U pytubefix`.

If `pytubefix` itself starts failing and `bgutil` is preferable, swap
`_download_audio` and `_yt_object` in `scripts/transcribe.py` for the
equivalent `yt-dlp` calls — the rest of the pipeline is unchanged.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `exit 3: missing_openai_key` | Whisper fallback fired but no key set | Set `OPENAI_API_KEY` or add it to a skill-local .env |
| `exit 3: openai_auth` | OpenAI rejected the key | Verify the key is current and has Whisper quota |
| `exit 2: video_unavailable` | Video is private, region-blocked, or deleted | Skip and move on |
| `exit 1: audio_download_failed` from pytubefix | YouTube reshaped mobile-client endpoints | `.venv/bin/pip install -U pytubefix` |
| `exit 1: audio_too_large` | Re-encoded audio still > 25 MB after segmentation | Inspect the video — likely 4+ hours of speech; consider preprocessing |
| `exit 1: openai_unavailable` (after retries) | OpenAI 429 or 5xx persisted | Wait a minute and retry; check status.openai.com |
| `exit 2: channel_unavailable` from `latest` | Handle typo or channel deleted | Fix the @handle in channels.txt |
