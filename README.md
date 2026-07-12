# Need Me Less 🧭

**Find out how often Claude Code stopped to ask you something — and fix it.**

Claude stopped and waited for you 182 times last week. That was ~13 hours of an
agent sitting blocked on a human answer — and 67% of the time, you just picked
the option it already recommended.

`need-me-less` audits your Claude Code transcripts, traces every interruption to
the exact config or skill that caused it, and publishes an interactive map where
each root cause comes with a ready-to-apply diff you stamp **Approve** or
**Reject**. Paste your decisions back, and Claude applies them. Each week, Claude
needs you a little less.

<!-- screenshot / demo gif here -->

## What it finds

- **Skill question gates** — skills that mandate `AskUserQuestion` stops
  ("STOP. You MUST ask NOW"), with the receipts: what % of your answers just took
  the recommended option (ceremony → automate) vs. free-text (real signal → batch,
  don't silence)
- **Plan-mode approval gates** — and how often they actually changed anything
- **Permission denials** — deny-list hits and missing MCP allowlists
- **Time cost** — how long Claude sat blocked per stop, per skill, per project
- **What NOT to fix** — it recommends *keeping* destructive-command guardrails and
  never allowlists mutating tools

## Install

```bash
git clone https://github.com/YOURUSER/need-me-less ~/.claude/skills/need-me-less
```

That's it. Claude Code picks up skills in `~/.claude/skills/` automatically.

## The prompt to toss Claude

> Run /need-me-less on my last week of conversations.

Or in your own words — the skill triggers on things like:

> How often did you need me this week? Audit it and show me what to change so you
> need me less.

Claude will scan your transcripts, investigate the causes, build the map, and hand
you a link. Stamp your decisions on the page, hit **Copy decisions for Claude**,
paste the block back into the session, and it applies exactly what you approved.

## Configuration

Say it in the prompt — the skill passes it through:

| What | How | Default |
|---|---|---|
| Audit window | "audit the last **30 days**" → `scan.py --days 30` | 7 days |
| Walk-away cap | "cap waits at **10 minutes**" → `build_page.py --cap 600` — waits longer than this count as you-were-away and are capped in totals | 30 min |

## Recording a demo? Retaking decisions?

Decisions are saved in your browser's localStorage, so they survive reloads. Two
ways to get a clean slate:

- **Reset button** in the bottom bar — clears all stamps instantly
- **`?fresh=1`** on the page URL — stateless mode: starts empty every load and
  never saves, perfect for multiple recording takes

## How it works

```
scan.py ──▶ interventions.json ──▶ Claude reads causes ──▶ cards.json ──▶ build_page.py ──▶ map.html
 (parses ~/.claude/projects/*.jsonl:      (reads settings.json,   (fix diffs +
  every AskUserQuestion + which option     SKILL.md gates,         recommendations)
  you picked, plan approvals, denials,     CLAUDE.md rules)
  interruptions, wait times)
```

Everything runs locally. Nothing leaves your machine except the map page you
choose to publish.

## Safety defaults

- Never recommends removing destructive-command deny rules (shows the diff,
  recommends **reject**)
- Never allowlists mutating MCP tools or arbitrary-code-execution commands
- Flags plugin-cache patches as ephemeral (overwritten on plugin update) and
  offers a durable CLAUDE.md override instead

## License

MIT
