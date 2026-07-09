# Finance brief template

Render `daily/<YYYY-MM-DD>.md` with exactly these sections in this order.
Aim for analyst-grade depth — assume the reader makes decisions from this
alone. 800–1500 words of substantive content.

```markdown
# Daily Brief — <YYYY-MM-DD>

_Generated from N new transcripts across M channels. Sources listed under
each section by `@handle:videoId`._

## Executive overview
2–3 paragraphs synthesizing the day's signal. What's the consensus take?
What's the biggest divergence? What's new versus yesterday? Lead with what an
analyst actually needs to know first.

## Tickers & themes

| Ticker / Theme | Channels covering | Net stance | Notes |
|---|---|---|---|
| AAPL | @meetkevin | bullish / mixed | one-line nuance |
| (theme: Fed rate path) | @MorningstarInc | — | one-line summary |

Cover every ticker and macro theme that appeared in ≥1 transcript. Don't
invent stances — quote what was actually said.

## Predictions registry

| Claim | Source | Timeframe | Conviction |
|---|---|---|---|
| "S&P hits 7k by year-end" | @meetkevin:abc123 | EOY 2026 | high |

Every explicit prediction with a timeframe goes here. Tag conviction as
`high` / `medium` / `low` / `speculative` based on the language used.

## Per-channel highlights

### @ChannelHandle — Video Title (videoId)
- 3–6 bullets of the most analyst-relevant content from this video
- Include numbers, quotes, frameworks
- Skip sponsor reads, channel housekeeping, filler

(Repeat for each new video captured this run.)

## Open questions for the analyst
- Claims worth verifying, conflicting views to reconcile, data points to
  pull from elsewhere.
```
