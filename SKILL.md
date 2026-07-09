---
name: follow-your-youtubers
description: |
  Track a list of YouTube channels and produce a daily digest brief. Use when
  the user wants a refresh of their followed channels — phrases like "follow
  my youtubers", "pull today's videos", "refresh the channel digest", "track
  the finance YouTubers". Reads handles from channels.txt, discovers new
  uploads for free, fetches transcripts through a fallback chain
  (transcriptapi if configured → free YouTube captions → OpenAI Whisper if
  configured), saves raw transcripts under transcripts/<handle>/, then writes
  a synthesis brief to daily/<YYYY-MM-DD>.md using the template selected in
  channels.txt (finance by default). Works with zero API keys.
required_environment_variables:
  - name: TRANSCRIPTAPI_API_KEY
    prompt: transcriptapi.com API key (optional — leave empty to skip)
    help: Optional. Unlocks the most reliable transcript backend (paid credits).
    required_for: the transcriptapi stage only; the skill works without it
  - name: OPENAI_API_KEY
    prompt: OpenAI API key (optional — leave empty to skip)
    help: Optional. Unlocks Whisper speech-to-text for caption-disabled videos (~$0.006/min).
    required_for: the Whisper fallback stage only; the skill works without it
metadata:
  category: media
  tags: [youtube, transcripts, digest, tracker, rss, whisper]
---

# follow-your-youtubers

Daily-digest skill for a fixed list of YouTube channels. Two outputs per run:
**raw transcripts** (one file per video, grouped by channel) and a **daily
brief** (one file per day). Channel discovery is always free. Transcripts go
through an ordered fallback chain, so the skill works with zero API keys and
gets more capable with each key you add.

## Path convention

All paths are **relative to this skill's own directory** (the folder
containing this SKILL.md). Resolve every path against that directory — do not
assume any other working directory. `.venv/bin/python` refers to the
skill-local virtualenv (see references/setup.md for first-run install).

## Inputs and outputs

- `channels.txt` — sibling of this SKILL.md. One channel per line. `#`
  comments and blank lines ignored. Re-read on every run.

  **Row format.** Whitespace-separated tokens. First token is `@handle`; any
  `key=value` token is a tag; anything else (e.g. a URL) is informational and
  ignored. A bare `key=value` line with no `@handle` is a **global
  directive**. Recognized:

  | Kind | Key | Values | Effect |
  | --- | --- | --- | --- |
  | directive | `template` | `finance` (default) \| `general` | Selects `templates/<value>.md` for the daily brief. |
  | tag | `lang` | ISO code, e.g. `zh` | Caption-language preference and Whisper language hint for that channel. |
  | tag | `backend` | `local` | Skip the transcriptapi stage for this channel (saves credits where it's known to fail, e.g. captions disabled). |

  Unknown keys: warn one line, never fatal. Empty channel list: stop and tell
  the user to add channels (see channels.example.txt).

- `transcripts/<handle>/<YYYY-MM-DD>_<videoId>.md` — raw transcripts.
  **The filesystem is the dedup ledger**: if a file matching this videoId
  already exists for the handle, the video is processed; skip it.

- `daily/<YYYY-MM-DD>.md` — the brief written at the end of each run.

If any directory or channels.txt is missing, create it (channels.txt by
copying channels.example.txt) and tell the user before continuing.

## Transcript backend chain

Per new video, try stages in order; first success wins. Log each fallthrough
inline (`@handle:<videoId>: stage failed — <reason>`).

1. **transcriptapi** — only if configured AND the channel is not tagged
   `backend=local`. Configured means: the `transcriptapi` skill is installed
   in your environment (preferred — use it per its own docs), or
   `TRANSCRIPTAPI_API_KEY` is set (call the HTTP API per transcriptapi.com
   docs). Costs 1 credit per transcript.
2. **Local captions** — free, no account:
   `.venv/bin/python scripts/fetch.py transcript --video-url <videoId> --no-whisper --format json`
   (append `--language <code>` when the channel has a `lang` tag).
3. **Whisper** — only if `OPENAI_API_KEY` resolves; ~$0.006/min:
   `.venv/bin/python scripts/fetch.py transcript --video-url <videoId> --format json`
   (same `--language` rule). The script runs captions first internally, so
   stage 3 also covers stage 2 — invoke stage 3 directly instead of stage 2
   when a Whisper key exists.

`fetch.py` prints one JSON object on stdout. Success shape matches
transcriptapi's `/transcript` response plus `source: "captions" | "whisper"`.
Errors: `{"error": kind, "detail": msg}` with exit codes 0 success · 1
transient (retry once) · 2 unavailable (skip) · 3 caller error (fix config).

## Workflow

1. **Load channels.** Parse channels.txt per the format above. Apply global
   directives; default `template=finance`.
2. **Per-channel cutoff.** For each handle, look in `transcripts/<handle>/`:
   max `YYYY-MM-DD` filename prefix if files exist, else today − 7 days.
3. **Discover new uploads (always free).** Preferred: transcriptapi's
   `channel/latest` (0 credits) when configured. Otherwise:
   `.venv/bin/python scripts/fetch.py latest --channel @HANDLE`
   → `{"channel": "@h", "results": [{"video_id", "title", "published", "url"}]}`.
   A single-channel failure must not abort the run — log inline, continue.
4. **Filter to new uploads.** Keep videos where BOTH: `published` is after the
   channel's cutoff, AND no `transcripts/<handle>/*_<videoId>.md` exists.
5. **Fetch and save transcripts.** Run each surviving video through the
   backend chain. On success write
   `transcripts/<handle>/<published-date>_<videoId>.md` using the transcript
   template below (create the folder if needed). On chain exhaustion: log,
   skip, never write a partial file. Retry a stage once only on exit 1.
6. **Write the daily brief.** After all fetches, write `daily/<today>.md`
   following the selected `templates/<name>.md`, covering ONLY transcripts
   captured this run. 800–1500 words of substance. Non-English content: the
   brief stays in English, but quote key numbers and claims in the original
   language with an English gloss. If `daily/<today>.md` exists from an
   earlier run today, append a `## Additional pull — HH:MM` section instead of
   overwriting. Zero new transcripts → no daily file; print the tally and stop.
7. **Tally** as the last line of your reply:
   `N channels checked, M new transcripts saved (A via transcriptapi, B via captions, C via whisper), K credits spent`
   — always show every line item, even when zero.

## Transcript file template

```markdown
---
title: "Video Title Goes Here"
channel: "@ChannelHandle"
published: 2026-07-01
url: https://youtube.com/watch?v=abc123XYZ00
videoId: abc123XYZ00
captured: 2026-07-08
language: en               # en | zh | zh-CN | ...
transcript_source: captions # transcriptapi | captions | whisper
---

<raw transcript text — keep paragraph breaks, do not summarize, do not strip
filler. This is the source of truth for re-summarization later.>
```

`transcript_source` values: `transcriptapi` (stage 1), `captions` (stage 2 or
fetch.py's captions path), `whisper` (fetch.py's Whisper path — copy the
`source` field from its output).

## Cost discipline

- Discovery is free at every stage. Local captions are free. transcriptapi
  costs 1 credit/video. Whisper costs ~$0.006/min (~$0.15 per 25-min video).
- Cutoff + filesystem dedup are the only guards against runaway spend. Never
  fetch a transcript unless both step-4 conditions hold.
- Watch the tally's `via whisper` figure run-to-run — a sudden jump means a
  channel's captions went dark.
- Backfills beyond the last 7 days: estimate first
  (`videos × 1 credit` and/or `captionless videos × ~$0.15`) and confirm with
  the user before fetching.

## Failure handling

- Single-channel discovery failure → log inline, continue with the rest.
- Single-video failure → fall through the chain; if exhausted, log and skip.
- transcriptapi 402 (out of credits) → disable stage 1 for the rest of the
  run; the chain continues at stage 2. Surface in the tally.
- fetch.py exit 3 (`missing_openai_key`, `openai_auth`) → disable stage 3 for
  the run; surface in the tally so the user knows to fix the key.
- fetch.py exit 1 (`openai_unavailable`, `audio_*`) → per-video transient;
  retry once, then skip that video and keep going.
- Bogus `@handle` → expected; report and move on.
