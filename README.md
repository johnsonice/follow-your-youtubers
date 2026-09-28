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

## Transcript backend chain

| Stage | Needs | Cost |
|---|---|---|
| 1. [transcriptapi.com](https://transcriptapi.com) | `TRANSCRIPTAPI_API_KEY` or the transcriptapi skill | 1 credit/video |
| 2. YouTube captions (local) | nothing | free |
| 3. OpenAI Whisper | `OPENAI_API_KEY` | ~$0.006/min |

Stages are optional top-down: with no keys at all, stage 2 still covers every
video that has captions in any language.

## Repo layout

- `SKILL.md` — the workflow Claude executes
- `scripts/fetch.py` — channel discovery (RSS) + transcript fetching CLI
- `templates/` — daily-brief styles (`finance`, `general`)
- `channels.txt` — your channel list (`channels.example.txt` = full reference)
