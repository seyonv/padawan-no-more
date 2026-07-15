# Padawan No More ⚔️

**Your Claude has been a padawan long enough. Run the Jedi Trials. Knight it.**

Last week, Claude-Wan Kenobi stopped mid-mission to ask for guidance **182 times**.
That was ~13 hours of a very capable Jedi standing in your doorway, waiting.
And 67% of the time, the guidance was… the option it had already recommended.

_"Master, shall I proceed?"_ — Yes.
_"Master, the recommended option?"_ — Yes.
_"Master—"_ — **YES.**

`padawan-no-more` audits your Claude Code transcripts, traces every interruption to
the exact config or skill gate that caused it, and publishes an interactive
**Trials map** where each root cause comes with a ready-to-apply diff you stamp
**Approve** or **Reject**. Paste your decisions back, and Claude applies them.
Each week, your padawan needs you a little less. That is the way of things.

<!-- demo video / screenshot here -->

## What the Trials reveal

- **Skill question gates** — skills that mandate `AskUserQuestion` stops
  ("STOP. You MUST ask NOW"), with the receipts: what % of your answers just took
  the recommended option (ceremony → automate) vs. free-text (real signal → batch,
  don't silence)
- **Plan-mode approval gates** — and how often they actually changed anything
- **Permission denials** — deny-list hits and missing MCP allowlists
- **Time cost** — how long your padawan stood waiting, per stop, per skill, per
  project, per day (the week's rhythm), plus the five single costliest stops
- **What NOT to fix** — it recommends _keeping_ destructive-command guardrails.
  A Jedi craves not `rm -rf`.

## Install

```bash
git clone https://github.com/YOURUSER/padawan-no-more ~/.claude/skills/padawan-no-more
```

That's it. Claude Code picks up skills in `~/.claude/skills/` automatically.

## The prompt to toss Claude

> Run /padawan-no-more on my last week of conversations.

Or in your own words — the skill triggers on things like:

> How often did you need me this week? You're not a padawan anymore — audit it and
> show me what to change.

Claude scans your transcripts, investigates the causes, builds the Trials map, and
hands you a link. Stamp your decisions on the page — mouse or keyboard
(`J`/`K` move between trials, `A` approve, `R` reject, `V` switch variant; the
saber in the bottom bar fills as you go and shows the waiting time your approvals
reclaim). Hit **Transmit decisions**, paste the block back into the session, and
it applies exactly what you approved.

## Configuration

Say it in the prompt — the skill passes it through:

| What          | How                                                                                                                                | Default |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Audit window  | "audit the last **30 days**" → `scan.py --days 30`                                                                                 | 7 days  |
| Walk-away cap | "cap waits at **10 minutes**" → `build_page.py --cap 600` — waits longer than this count as you-were-away and are capped in totals | 30 min  |

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

MIT. Not affiliated with, endorsed by, or associated with Lucasfilm or Disney —
this is a fan-flavored developer tool that uses "padawan" the way your team lead
does.
