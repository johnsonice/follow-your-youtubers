# follow-your-youtubers

A [Claude Code skill](https://code.claude.com/docs/en/skills) that follows a
list of YouTube channels, pulls transcripts of new uploads, and writes a
daily digest brief. Works with **zero API keys** out of the box; add keys to
unlock more capable transcript backends.

## What a run produces

- `transcripts/<handle>/<date>_<videoId>.md` — one raw transcript per new video
- `daily/<YYYY-MM-DD>.md` — a synthesized daily brief (finance-analyst style
  by default; a general style is included)

## Install

Three routes — pick one:

**Claude Code plugin (official):**

```
/plugin marketplace add johnsonice/follow-your-youtubers
/plugin install follow-your-youtubers
```

**Skills CLI (works across agents — Claude Code, Cursor, Codex, …):**

```bash
npx skills add johnsonice/follow-your-youtubers
```

**Manual clone:**

```bash
git clone https://github.com/johnsonice/follow-your-youtubers.git ~/.claude/skills/follow-your-youtubers
```

**Then, whichever route you used — one-time Python setup** inside the
installed skill directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Full first-run details (ffmpeg, keys): [references/setup.md](references/setup.md).

## Use

In Claude Code, from any project:

> follow my youtubers

Claude reads `channels.txt`, checks each channel for new uploads (free),
fetches transcripts through the backend chain, and writes the daily brief.
Edit `channels.txt` to change the list — see `channels.example.txt` for the
full format. Every channel row needs a `lang=` tag (e.g. `lang=en`,
`lang=zh`) so auto-dubbed videos don't come back in the wrong language.

Each run looks back 7 days, so a video older than that is skipped, even
after missed runs. YouTube Shorts are skipped too, which keeps the number
of YouTube requests down.

The brief is written in the language you ask in. "follow my youtubers" gets
an English brief, and "拉一下今天的视频" gets a Chinese one. You can also name
the language directly ("write the brief in Japanese"). This is separate from
the channels' `lang=` tags, so a Chinese brief can cover English channels.

## Transcript backend chain

`scripts/fetch.py transcript` tries these in order and stops at the first
success:

| Stage | Needs | Cost |
|---|---|---|
| 1. yt-dlp with your YouTube cookies | `YT_COOKIES_FILE` or `YT_COOKIES_BROWSER` | free |
| 2. YouTube captions, then yt-dlp without cookies | nothing (`YT_PROXY` optional) | free |
| 3. OpenAI Whisper | `OPENAI_API_KEY` | ~$0.006/min |
| 4. [transcriptapi.com](https://transcriptapi.com) | `TRANSCRIPT_API_KEY` | 1 credit/video |

Every stage except 2 is optional. With nothing configured, stage 2 still
covers every video that has captions in any language. Stage 4 runs only when
stages 1–3 all failed. Without a key it is skipped, and the skip is written
to `transcripts/skipped.jsonl`.

## Deliver transcripts to a memory vault

If the omniverse-memory skill is installed and configured, each run sends the day's transcripts to that vault as sources:

```bash
.venv/bin/python scripts/deliver_memory.py --from 2026-10-20 --to 2026-10-24
```

Each transcript is captured once under `youtube:<videoId>`, so rerunning is safe. Without omniverse-memory the script prints a skip notice and exits 0.

## Getting past YouTube IP blocks

When YouTube answers `IpBlocked` / `RequestBlocked`, configure one or both of
these in the skill-local `.env` (gitignored).

**Cookies (first choice, free).** yt-dlp sends the cookies of a logged-in
YouTube session, which YouTube throttles far less than anonymous requests.

- `YT_COOKIES_FILE=/absolute/path/to/youtube-cookies.txt`. A Netscape-format
  file. Export it from a logged-in browser window with a cookies.txt
  extension, or run
  `yt-dlp --cookies-from-browser chrome --cookies youtube-cookies.txt --skip-download https://www.youtube.com/watch?v=dQw4w9WgXcQ`
  once. Prefer this for scheduled runs: it never triggers a macOS Keychain
  prompt.
- `YT_COOKIES_BROWSER=chrome` (or `chrome:Profile 1`, `firefox`, `safari`).
  yt-dlp reads cookies straight from the browser on every call. On macOS
  the first Chrome read asks for Keychain access ("Chrome Safe Storage").
  Click "Always Allow" once, or an unattended run will sit on the prompt.
- If both are set, `YT_COOKIES_FILE` wins.
- Use a throwaway Google account if you can. YouTube can flag accounts
  whose cookies make automated requests.

**transcriptapi.com (last resort, paid per transcript).** It fetches the
transcript on its own servers, so it works even while this machine is
blocked.

1. Sign up at https://transcriptapi.com. A free account comes with 100
   credits and needs no card. The Starter plan is $5/month for 1,000
   credits.
2. Copy the API key from the dashboard. It starts with `sk_`.
3. Add `TRANSCRIPT_API_KEY=sk_...` to `.env`. The older name
   `TRANSCRIPTAPI_API_KEY` still works.
4. Each transcript costs 1 credit. Add `--no-transcriptapi` (or tag the
   channel `backend=local`) where it isn't worth paying, e.g. channels with
   captions disabled.

## Repo layout

- `SKILL.md` — the workflow Claude executes
- `scripts/fetch.py` — channel discovery (RSS) + transcript fetching CLI
- `templates/` — daily-brief styles (`finance`, `general`)
- `channels.txt` — your channel list (`channels.example.txt` = full reference)
