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
  | tag | `lang` | ISO code, e.g. `en`, `zh` — **required on every channel row** | Pins the caption track and the Whisper language hint for that channel. |
  | tag | `backend` | `local` | Skip the transcriptapi stage for this channel (saves credits where it's known to fail, e.g. captions disabled). |

  **Why `lang` is required.** Videos with YouTube auto-dubbing list ~20
  auto-generated caption tracks, one per dubbed language. Without a language,
  fetch.py's auto mode takes the first track, which is often not the language
  spoken in the video (an English video came back as Arabic captions). A
  channel row without `lang=` → warn one line, skip that channel for this run,
  and tell the user to add the tag. Never fall back to auto mode.

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
   `.venv/bin/python scripts/fetch.py transcript --video-url <videoId> --language <lang> --no-whisper --format json`
   (always pass the channel's `lang` tag as `--language`).
3. **Whisper** — only if `OPENAI_API_KEY` resolves; ~$0.006/min:
   `.venv/bin/python scripts/fetch.py transcript --video-url <videoId> --language <lang> --format json`
   (same `--language` rule). The script runs captions first internally, so
   stage 3 also covers stage 2 — invoke stage 3 directly instead of stage 2
   when a Whisper key exists.

`fetch.py` prints one JSON object on stdout. Success shape matches
transcriptapi's `/transcript` response plus `source: "captions" | "whisper"`.
Errors: `{"error": kind, "detail": msg}` with exit codes 0 success · 1
transient (retry once — except IP blocks, see below) · 2 unavailable (skip) ·
3 caller error (fix config).

## YouTube request discipline (avoid IP blocks)

YouTube blocks an IP for hours once it sees a burst of requests. On an
earlier test run, 10 parallel discovery calls, ~90 watch-page scrapes
(8 at a time), and 6 parallel transcript fetches got every caption request
answered with `IpBlocked`. Retrying did not help. Only switching networks
did. Every rule below exists to keep a run from doing that again.

- **One YouTube request at a time.** Run every `fetch.py` call serially:
  no `&`, no parallel tool calls, no thread pools, no subagents fetching
  side by side.
- **Pause between calls:** `sleep 3` between `latest` calls, `sleep 5`
  between `transcript` calls (run them in one serial shell loop). There is
  no cap on how many videos a run fetches. Big runs just take longer
  (100 videos ≈ 10+ minutes), and that's the point.
- **Only the requests the workflow needs:** one `latest` per channel, one
  `transcript` per new video. Never scrape channel or watch pages to
  pre-check dates, durations, or caption availability. `published` from
  discovery is enough to filter, and fetch.py returns the metadata itself.
- **Circuit breaker — stop on the first block.** If any fetch.py error
  detail contains `IpBlocked` or `RequestBlocked`, or YouTube answers
  HTTP 429:
  1. Stop all YouTube requests for the rest of the run.
  2. Do not retry. Retries extend the block.
  3. Do not route the remaining videos through Whisper as a workaround.
     That spends money and still downloads the audio from YouTube.
  4. Keep what was saved, write the brief if any transcripts were
     captured, and tell the user to switch networks (toggle the VPN or use
     a phone hotspot) or wait a few hours before the next run.
- **RSS outage ≠ bad handles.** If `latest` fails with `rss_fetch_failed`
  (`RSS feed returned 404`) on 2 channels in a row, YouTube's feed endpoint
  is down. It has failed intermittently since Dec 2025. Stop discovery
  instead of looping through the rest of the list. Use transcriptapi's
  `channel/latest` if configured; otherwise report the outage and stop.

## Workflow

1. **Load channels.** Parse channels.txt per the format above. Apply global
   directives; default `template=finance`. Skip (and warn about) any channel
   row without a `lang=` tag.
2. **Per-channel cutoff.** For each handle, look in `transcripts/<handle>/`:
   max `YYYY-MM-DD` filename prefix if files exist, else today − 7 days.
3. **Discover new uploads (always free).** Preferred: transcriptapi's
   `channel/latest` (0 credits) when configured. Otherwise:
   `.venv/bin/python scripts/fetch.py latest --channel @HANDLE`
   → `{"channel": "@h", "results": [{"video_id", "title", "published", "url"}]}`.
   Channels one at a time with a pause between each (see YouTube request
   discipline). A single-channel failure must not abort the run — log
   inline, continue — unless the RSS-outage rule applies.
4. **Filter to new uploads.** Keep videos where BOTH: `published` is after the
   channel's cutoff, AND no `transcripts/<handle>/*_<videoId>.md` exists.
5. **Fetch and save transcripts.** Run each surviving video through the
   backend chain, one video at a time with a pause between each. On success
   write `transcripts/<handle>/<published-date>_<videoId>.md` using the
   transcript template below (create the folder if needed). On chain
   exhaustion: log, skip, never write a partial file. Retry a stage once only
   on exit 1, and never on an IP block: trip the circuit breaker instead.
6. **Write the daily brief.** After all fetches, write `daily/<today>.md`
   following the selected `templates/<name>.md`, covering ONLY transcripts
   captured this run. 800–1500 words of substance. Non-English content: the
   brief stays in English, but quote key numbers and claims in the original
   language with an English gloss. If `daily/<today>.md` exists from an
   earlier run today, append a `## Additional pull — HH:MM` section instead of
   overwriting. Zero new transcripts → no daily file; print the tally and stop.
7. **Tally** as the last line of your reply:
   `N channels checked, M new transcripts saved (A via transcriptapi, B via captions, C via whisper), K credits spent`
   — always show every line item, even when zero. If the circuit breaker
   tripped or channels were skipped for a missing `lang=`, say so (with
   counts) in one line right above the tally.

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
  the user before fetching. Backfills still obey YouTube request discipline.

## Failure handling

- Single-channel discovery failure → log inline, continue with the rest.
- Single-video failure → fall through the chain; if exhausted, log and skip.
- transcriptapi 402 (out of credits) → disable stage 1 for the rest of the
  run; the chain continues at stage 2. Surface in the tally.
- fetch.py exit 3 (`missing_openai_key`, `openai_auth`) → disable stage 3 for
  the run; surface in the tally so the user knows to fix the key.
- fetch.py exit 1 (`openai_unavailable`, `audio_*`, `captions_fetch_failed`
  without an IP block) → per-video transient; retry once, then skip that
  video and keep going.
- `IpBlocked` / `RequestBlocked` / HTTP 429 from YouTube → circuit breaker
  (see YouTube request discipline): stop all YouTube requests, no retries,
  no Whisper workaround, tell the user to switch networks or wait.
- `rss_fetch_failed` 404 on 2 channels in a row → RSS endpoint outage, not
  bad handles; stop discovery and report.
- Bogus `@handle` → expected; report and move on.
