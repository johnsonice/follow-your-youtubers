---
name: follow-your-youtubers
description: |
  Track a list of YouTube channels and produce a daily digest brief. Use when
  the user wants a refresh of their followed channels — phrases like "follow
  my youtubers", "pull today's videos", "refresh the channel digest", "track
  the finance YouTubers". Reads handles from channels.txt, discovers new
  uploads for free, fetches transcripts through a fallback chain
  (yt-dlp with browser cookies if configured → free YouTube captions →
  OpenAI Whisper if configured → transcriptapi.com as a paid last resort if
  configured), saves raw transcripts under transcripts/<handle>/, then writes
  a synthesis brief to daily/<YYYY-MM-DD>.md using the template selected in
  channels.txt (finance by default). The brief is written in whatever
  language the user asks for, or else the language of the request. Works
  with zero API keys.
required_environment_variables:
  - name: TRANSCRIPT_API_KEY
    prompt: transcriptapi.com API key, starts with sk_ (optional — leave empty to skip)
    help: Optional. Last-resort transcript backend when YouTube blocks this IP (1 credit per transcript).
    required_for: the transcriptapi fallback only; the skill works without it
  - name: YT_COOKIES_FILE
    prompt: Path to a Netscape cookies.txt exported from a logged-in YouTube session (optional)
    help: Optional. yt-dlp sends these cookies first, which often gets past IP blocks. Wins over YT_COOKIES_BROWSER.
    required_for: the cookies stage only
  - name: YT_COOKIES_BROWSER
    prompt: Browser for yt-dlp --cookies-from-browser, e.g. chrome or "chrome:Profile 1" (optional)
    help: Optional. Same as YT_COOKIES_FILE but reads cookies straight from the browser.
    required_for: the cookies stage only
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
  | tag | `backend` | `local` | Never fall back to transcriptapi for this channel: pass `--no-transcriptapi` (saves credits where it's known to fail, e.g. captions disabled). |

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

The whole chain runs inside one `fetch.py` call per video. First success
wins:

1. **yt-dlp with cookies.** Only if `YT_COOKIES_FILE` or `YT_COOKIES_BROWSER`
   is set. Logged-in cookies often get past an IP block. Free.
2. **YouTube captions** (youtube-transcript-api), then **yt-dlp without
   cookies**. Both honour `YT_PROXY`. Free.
3. **Whisper.** Only if `OPENAI_API_KEY` resolves and `--no-whisper` is not
   passed. ~$0.006/min.
4. **transcriptapi.com.** Only if `TRANSCRIPT_API_KEY` (or the older
   `TRANSCRIPTAPI_API_KEY`) is set, every stage above failed, and
   `--no-transcriptapi` is not passed. 1 credit per transcript. It does not
   touch YouTube from this machine. Without a key the stage is skipped and
   the skip is recorded in `transcripts/skipped.jsonl`.

The command:
`.venv/bin/python scripts/fetch.py transcript --video-url=<videoId> --language <lang> --format json`
- Always pass the channel's `lang` tag as `--language`.
- Always use the `--video-url=<videoId>` form. A videoId starting with `-`
  is otherwise parsed as a flag and fails with `bad_args`.
- Add `--no-whisper` when no Whisper key exists, and `--no-transcriptapi`
  for channels tagged `backend=local`.

`fetch.py` prints one JSON object on stdout. Success shape matches
transcriptapi's `/transcript` response plus
`source: "captions" | "whisper" | "transcriptapi"`. A `transcriptapi` result
also carries `metadata.youtube_error`, the YouTube failure that forced it.
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
- **Redirect each call's stdin in that loop:** write
  `fetch.py transcript ... < /dev/null`. fetch.py already keeps ffmpeg and
  yt-dlp off stdin, but a `while read` loop still loses its queued lines to
  any child that reads stdin. On 10-16 that sent a RhinoFinance transcript
  to `transcripts/@inance/`.
- **Only the requests the workflow needs:** one `latest` per channel, one
  `transcript` per new video. Never scrape channel or watch pages to
  pre-check dates, durations, or caption availability. `published` from
  discovery is enough to filter, and fetch.py returns the metadata itself.
- **Circuit breaker — stop on the first block.** If any fetch.py error
  detail, or a `transcriptapi` result's `metadata.youtube_error`, contains
  `IpBlocked` or `RequestBlocked`, or YouTube answers HTTP 429:
  1. Stop all YouTube requests for the rest of the run.
  2. Do not retry. Retries extend the block.
  3. Do not route the remaining videos through Whisper as a workaround.
     That spends money and still downloads the audio from YouTube.
  4. If `TRANSCRIPT_API_KEY` is set, keep going with the remaining
     videos using `--transcriptapi-only`, which sends no YouTube request.
     Skip channels tagged `backend=local`.
  5. Keep what was saved, write the brief if any transcripts were
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
2. **Cutoff (lookback window).** cutoff = today − 7 days, the same for every
   channel. The skill is about freshness, so it never reaches further back,
   even after missed runs: videos older than 7 days are dropped, not caught
   up. The cutoff only limits how far back to look. Step 4's videoId check
   is what prevents refetching. (A cutoff at the newest saved date
   permanently dropped a second video published the same day, and every
   video that failed on an earlier run.)
3. **Discover new uploads (always free).** Preferred: transcriptapi's
   `channel/latest` (0 credits) when configured. Otherwise:
   `.venv/bin/python scripts/fetch.py latest --channel @HANDLE`
   → `{"channel": "@h", "results": [{"video_id", "title", "published", "url", "is_short"}], "shorts_skipped": N}`.
   **Shorts are skipped by default.** The RSS link of a Short is
   `/shorts/<id>`, so `latest` drops them with no extra request and reports
   how many in `shorts_skipped`. They are mostly clips of longer videos and
   only add YouTube requests. Pass `--include-shorts` only if the user asks
   for Shorts. With transcriptapi's `channel/latest`, drop Shorts the same
   way if its rows expose them.
   Channels one at a time with a pause between each (see YouTube request
   discipline). A single-channel failure must not abort the run — log
   inline, continue — unless the RSS-outage rule applies.
4. **Filter to new uploads.** Keep videos where BOTH: the date part of
   `published` is on or after the channel's cutoff (`>=`, not `>`), AND no
   `transcripts/<handle>/*_<videoId>.md` exists. A video that failed on an
   earlier run has no file, so it comes back here and is retried
   automatically while it is inside the window.
5. **Fetch and save transcripts.** Run each surviving video through the
   backend chain, one video at a time with a pause between each. On success
   write `transcripts/<handle>/<published-date>_<videoId>.md` using the
   transcript template below (create the folder if needed). On chain
   exhaustion: log, skip, never write a partial file. Retry a stage once only
   on exit 1, and never on an IP block: trip the circuit breaker instead.
6. **Write the daily brief.** After all fetches, write `daily/<today>.md`
   following the selected `templates/<name>.md`, covering ONLY transcripts
   captured this run. 800–1500 words of substance. Write it in the brief
   language (see "Brief language" below). If `daily/<today>.md` exists from an
   earlier run today, append a `## Additional pull — HH:MM` section (heading
   translated into the brief language) instead of overwriting. Zero new
   transcripts → no daily file; print the tally and stop.
7. **Tally** as the last line of your reply:
   `N channels checked, M new transcripts saved (A via transcriptapi, B via captions, C via whisper), K credits spent`
   — always show every line item, even when zero. If the circuit breaker
   tripped or channels were skipped for a missing `lang=`, say so (with
   counts) in one line right above the tally.

## Brief language

The daily brief and your reply are written in one **brief language**, which
any language can be. To pick it:

1. If the user's request names an output language ("write the brief in
   Japanese", "用中文输出"), use that language.
2. Otherwise, use the language the user's request is written in. "follow my
   youtubers" → English. "拉一下今天的视频" → Chinese.

The brief language has nothing to do with a channel's `lang=` tag. That tag
only picks the caption track to fetch. An English request over Chinese
channels gets an English brief, and the reverse holds too.

In the brief language:
- Translate the template's headings and table column names. Keep the section
  order the template sets.
- Write all prose and table text in it. Leave tickers, `@handle`s, videoIds,
  numbers, price levels and proper nouns unchanged.
- If a source is in the brief language, quote it directly. If it's in another
  language, quote the key numbers and claims in the original and add a short
  gloss in the brief language. Example: 「预计能提升年度EPS5%左右」 ("about +5%
  annual EPS") in an English brief.
- Never translate the transcript files. They stay raw source text.
- The step-7 tally line keeps its fixed English format, so runs can be
  compared over time.

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

`transcript_source`: copy the `source` field from fetch.py's output
(`captions`, `whisper` or `transcriptapi`).

## Cost discipline

- Discovery is free at every stage. Local captions are free. transcriptapi
  costs 1 credit/video. Whisper costs ~$0.006/min (~$0.15 per 25-min video).
- Cutoff + filesystem dedup are the only guards against runaway spend. Never
  fetch a transcript unless both step-4 conditions hold.
- Retries are bounded by the window, with no separate failure ledger. A
  video that keeps failing (e.g. a captionless video whose Whisper upload
  errors) is retried once per run until its published date falls before the
  cutoff: at most ~7 daily runs.
- Watch the tally's `via whisper` figure run-to-run — a sudden jump means a
  channel's captions went dark.
- Backfills (videos published before the step-2 cutoff) happen only when
  the user explicitly asks: estimate first
  (`videos × 1 credit` and/or `captionless videos × ~$0.15`) and confirm with
  the user before fetching. Never offer or suggest one on your own: missed
  runs and blocked videos that age out of the window are simply dropped.
  Backfills still obey YouTube request discipline.

## Failure handling

- Single-channel discovery failure → log inline, continue with the rest.
- Single-video failure → fall through the chain; if exhausted, log and skip.
  No file is written, so later runs retry it while it is inside the step-2
  window.
- transcriptapi out of credits (`transcriptapi_no_credits` in the error
  detail) → pass `--no-transcriptapi` for the rest of the run. Surface in
  the tally.
- fetch.py exit 3 `bad_cookies_file` → `YT_COOKIES_FILE` points nowhere.
  Stop and tell the user. Every video would fail the same way.
- fetch.py exit 3 (`missing_openai_key`, `openai_auth`) → pass `--no-whisper` for
  the run; surface in the tally so the user knows to fix the key.
- fetch.py exit 1 (`openai_unavailable`, `audio_*`, `captions_fetch_failed`
  without an IP block) → per-video transient; retry once, then skip that
  video and keep going.
- `IpBlocked` / `RequestBlocked` / HTTP 429 from YouTube → circuit breaker
  (see YouTube request discipline): stop all YouTube requests, no retries,
  no Whisper workaround, finish with `--transcriptapi-only` if a key is
  set, tell the user to switch networks or wait.
- `rss_fetch_failed` 404 on 2 channels in a row → RSS endpoint outage, not
  bad handles; stop discovery and report.
- Bogus `@handle` → expected; report and move on.
