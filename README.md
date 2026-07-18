# Padawan No More ⚔️

**Your Claude has been a padawan long enough. Run the Jedi Trials. Knight it.**

Last week, Claude-Wan Kenobi stopped mid-mission to ask for guidance **129 times** —
about 9 hours of a very capable Jedi standing in your doorway, waiting.
And 80% of the time, your answer was… the option he had already recommended.

> _"Master, shall I proceed?"_ — Yes.
> _"Master, the recommended option?"_ — Yes.
> _"Master—"_ — **YES.**

`padawan-no-more` is a Claude Code skill that audits your transcripts, traces every
stop to the exact config or skill gate that caused it, and publishes an interactive
**Trials map** — each root cause paired with a ready-to-apply diff you stamp
**Approve** or **Reject**. Paste your decisions back, and Claude applies exactly
what you approved. Each week, your padawan needs you a little less.

![The Trials map](docs/screenshots/trials-map.png)

## Install

One command, pick your flavor:

```bash
npx skills add seyonv/padawan-no-more
```

or as a Claude Code plugin:

```
/plugin marketplace add seyonv/padawan-no-more
/plugin install padawan-no-more@padawan-no-more
```

or the classic way:

```bash
git clone https://github.com/seyonv/padawan-no-more ~/.claude/skills/padawan-no-more
```

Pick **one** — each method installs a full copy, and two copies means Claude
sees the skill twice.

## Run it

> Run /padawan-no-more on my last week of conversations.

Or in your own words — the skill triggers on things like:

> How often did you need me this week? You're not a padawan anymore — audit it
> and show me what to change.

Claude scans your transcripts, investigates the causes, builds the Trials map,
and hands you a link. Stamp, transmit, paste — done.

**Light week?** If the scan finds too few stops to be interesting, ask for the
**training simulation** — a full map built from bundled example data, clearly
stamped as such — or widen the window ("audit the last 30 days").

## How it works — three stamps and you're done

1. **Read each trial** — one card per root cause, costliest first, with the
   evidence (how often it stopped you, what it cost) and the exact file responsible.
2. **Stamp Approve or Reject** — mouse, or keyboard: `J`/`K` move between trials,
   `A` approve, `R` reject, `V` switch fix variant.
3. **Transmit** — copy the decision block, paste it into your Claude Code session,
   and only the approved diffs are applied. Nothing changes until you transmit.

As you decide, Claude the Padawan — the starburst in robes with a braid — levels
up in the corner: robe, belt, saber hilt… and when the last trial is decided, the
blade ignites and the braid is cut.

![Knighted — padawan no more](docs/screenshots/knighted.png)

When the last trial is decided, **Share the verdict** appears: a PNG card with
your week's numbers — stops, hours waiting, first-option rate, time reclaimed —
rendered entirely on your machine. Save it, post it, flex it.

## What the Trials reveal

| Signal                   | What you learn                                                                                                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Skill question gates** | Which skills mandate `AskUserQuestion` stops — with receipts: % of answers that just took the recommended option (ceremony → automate) vs. free-text (real signal → batch, don't silence) |
| **Plan-mode approvals**  | How often plan gates actually changed anything                                                                                                                                            |
| **Permission denials**   | Deny-list hits and missing MCP allowlists                                                                                                                                                 |
| **Time cost**            | Waiting time per stop, skill, project, and day — plus the five single costliest stops, with exact durations                                                                               |
| **What NOT to fix**      | It recommends _keeping_ destructive-command guardrails. A Jedi craves not `rm -rf`.                                                                                                       |

![A trial card with its fix diff](docs/screenshots/trial-card.png)

## Configuration

Say it in the prompt — the skill passes it through:

| What          | How                                                                                                                                                                           | Default |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| Audit window  | "audit the last **30 days**" → `scan.py --days 30`                                                                                                                            | 7 days  |
| Walk-away cap | "cap waits at **10 minutes**" → `build_page.py --cap 600` — waits longer than this count as you-were-away and are capped in the totals (exact durations still shown per stop) | 30 min  |

## Recording a demo? Retaking decisions?

Decisions are saved in localStorage, scoped to each audit's date range, so they
survive reloads without bleeding between weeks. For a clean slate:

- **Reset** in the bottom bar — clears all stamps instantly
- **`?fresh=1`** on the page URL — stateless mode: starts empty every load and
  never saves. Perfect for multiple recording takes.

## Under the hood

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

> _"Approve, or approve not. There is no 'ask again later.'"_ — the Council

## License

MIT. Not affiliated with, endorsed by, or associated with Lucasfilm or Disney —
this is a fan-flavored developer tool that uses "padawan" the way your team lead
does.
