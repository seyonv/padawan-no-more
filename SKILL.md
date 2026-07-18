---
name: padawan-no-more
description: Use when the user wants to know how often Claude stopped for human input, reduce permission prompts or approval gates, measure time spent waiting for answers, audit AskUserQuestion/plan-mode interruptions, or make Claude Code more autonomous ("need me less", "padawan no more", "knight my claude", "run the jedi trials", "stop asking me so many questions", "why did you block on that", "intervention audit").
---

# Padawan No More

Your padawan keeps stopping mid-mission to ask for guidance. Audit every point where Claude Code stopped and waited for a human, trace each stop
to the config or skill that caused it, and publish an interactive map with
ready-to-apply fix diffs the user approves or rejects.

## Overview

Interventions come from five places, and each has a different lever:

| Source                               | Lever                                                                               |
| ------------------------------------ | ----------------------------------------------------------------------------------- |
| Skill-mandated AskUserQuestion gates | Patch the skill, or a CLAUDE.md override (CLAUDE.md outranks skills)                |
| Plan-mode approval (ExitPlanMode)    | CLAUDE.md rules that route into plan mode; `--permission-mode acceptEdits` headless |
| Permission denials                   | `permissions.deny` / missing `permissions.allow` in settings.json                   |
| MCP servers with no allowlist entry  | project `.claude/settings.json` allow rules (read-only tools only)                  |
| User interruptions (Escape)          | Not config — report, don't "fix"                                                    |

**Core judgment rule — read the first-option rate before proposing a fix:**
a gate whose answers are ≥80% first-option is ceremony (automate it: auto-decide +
log); a gate with heavy free-text answers is extracting real intent (don't silence
it — make it non-blocking when the user is away, and batch questions).

## Mission log (how to narrate the run)

Present the run as a live mission log so the user watches the Trials assemble.
Print this checklist as a fenced code block after EACH phase completes, updating
statuses in place — ✦ done (with real numbers), ▸ running, ○ waiting:

```
⚔  THE JEDI TRIALS ────────────────────────────────
✦  Scan the archives      133 sessions · 129 stops · 9h 12m waiting
✦  Trace each cause       3 skill gates + settings.json
▸  Author the trials      II of V — map is live, assembling
   ✦  Trial I   plan-exit-review          ⏱ 4h 23m
   ▸  Trial II  brainstorming gates…
○  Raise the map
```

Rules: keep exactly these four phase names; under "Author the trials", add one
sub-line per trial as it lands (✦ done with its wait cost, ▸ in progress);
fill in the numbers from real output (scan.py and build_page.py print their
own ⚔ summary boxes — let those show too, don't suppress them); never fake a
number. The browser page (opened right after the scan) is the primary
experience — it live-updates on its own; this terminal log is the co-pilot
narration, not the main show. After the final phase, close with one line:

```
⚔  The map awaits your judgment, Master.        (already open in your browser)
```

## Procedure

1. **Scan** (deterministic): `python3 scripts/scan.py --days 7 --out interventions.json`
   — parses `~/.claude/projects/*/*.jsonl`, emits every intervention event with the
   skill in effect, which option the user picked, and `wait_s` (how long Claude sat
   blocked). Default window is 7 days; the user can ask for any `--days N`.

   **Then open the live page immediately — within seconds of the scan, before
   any tracing.** Write `cards.json` with just `meta.range` and `"cards": []`,
   build with `--state scanning`, and open it in the user's browser:

   ```
   python3 scripts/build_page.py --scan interventions.json --cards cards.json \
       --template assets/template.html --state scanning --out map.html
   open map.html
   ```

   While assembling, the page reloads itself every few seconds — it IS the
   progress display. Every rebuild you do from here on appears in the user's
   browser automatically; never tell them to refresh.

2. **Trace causes.** For each major event cluster, read the actual config:
   - `~/.claude/settings.json` and project `.claude/settings.json` (allow/deny/ask)
   - the SKILL.md of any skill that generated ≥5 dialogs — find the literal lines
     that mandate questions (e.g. "STOP. You MUST call AskUserQuestion")
   - `~/.claude/CLAUDE.md` rules that mandate skills or plan mode
     Distinguish user-owned skills (`~/.claude/skills/…`, patchable) from plugin-cache
     skills (`~/.claude/plugins/cache/…`, overwritten on update → prefer a CLAUDE.md
     override and say so in the card).

3. **Author the trials into the live page.** As soon as the trace names the
   root causes, decide the trial count N and rebuild with
   `--state authoring --total N` — the user's page flips from "tracing each
   cause" to N shimmer-skeleton trials. Then:
   - Author cards one at a time in `cards.json` (schema at the top of
     `scripts/build_page.py`), ordered by wait-time cost. **Rebuild after every
     single card** with the same `--state authoring --total N` flags — each
     rebuild flips one skeleton into a real trial on the user's screen. The
     rebuild costs nothing; the delight of watching trials land is the point.
   - Each card: what happened (with the first-option % as evidence), a `cause`
     box naming the exact file, and 1–2 fix **variants** with real unified-diff
     hunks. Every variant needs a one-line `name` — it labels the decision in
     the transmission. Recommendations: never recommend removing
     destructive-command deny rules (present the diff, recommend reject); never
     allowlist mutating MCP tools or arbitrary code execution; mark
     plugin-cache patches as ephemeral.

4. **Final build**: rebuild with `--state complete` (drop `--total`) — the
   page stops self-reloading, the build meter becomes the decision saber, and
   Transmit unlocks. Optionally also publish `map.html` as an artifact if the
   user wants a durable/shareable link — the local page is the primary
   experience. The page (Claude-styled light theme)
   has a sticky sidebar rail (mascot, decided-count, section nav with per-trial
   ✓/✕ marks), approve/reject stamps per fix, a variant chooser, wait-time
   totals, a per-day rhythm chart, the five costliest single stops (exact
   durations, deduped per dialog), per-project intervention rates, and a
   first-option breakdown. Keyboard: J/K move between trials, A approve, R
   reject, V switch variant; the bottom bar shows progress and the waiting time
   approvals would reclaim, and the sidebar's Claude-starburst padawan levels
   up toward Jedi as trials are decided (braid cut at the last one). `?fresh=1`
   gives a stateless page for demo recordings; the Reset button clears saved
   decisions (decisions are stored per audit date range). When the last trial
   is decided, a **Share the verdict** button appears in the bottom bar — it
   renders a PNG card (stops, waiting time, first-option rate, time reclaimed)
   on a local canvas the user can save or copy; nothing is uploaded.

5. **Apply decisions.** The page's "Transmit decisions" button produces a
   self-contained block (header: "Padawan-No-More decisions") that carries the
   full unified diff for every approved fix — file path + hunks, verbatim.
   When the user pastes it (into any session, this skill loaded or not): apply
   exactly those diffs, nothing more; skip rejected and undecided trials; if a
   hunk no longer matches the target file, stop and show the conflict instead
   of improvising; confirm each file touched.

## Demo mode (training simulation)

If the scan finds fewer than 15 interventions (scan.py prints a hint when so),
the map will be thin and the first-run experience poor. Tell the user, then
offer two options: widen the window (`--days 30`), or run the training
simulation — build straight from the bundled example data, skipping the trace
and authoring phases:

```
python3 scripts/build_page.py --scan examples/interventions.example.json \
    --cards examples/cards.example.json --template assets/template.html \
    --demo --out map.html
```

`--demo` stamps the page with a "training simulation — example data" chip.
Never present simulation numbers as the user's own audit, and never apply the
example cards' diffs — the transmission from a demo page is for looking at,
not for pasting.

## Configuration

- `--days N` — audit window (default 7)
- `--cap SECONDS` on build_page.py — wait time above this counts as a walk-away
  and is capped in totals (default 1800)
- `--demo` on build_page.py — marks the page as a training simulation (see above)
- `--state scanning|authoring|complete` + `--total N` on build_page.py —
  non-complete states render skeleton trials for the cards not yet authored,
  show a build meter in place of Transmit, put the mascot in training, and
  make the page reload itself every ~4s so rebuilds appear live

## Common mistakes

- Counting only permission prompts: on permissive setups (`Bash(*)` allowed),
  ~80% of interventions come from skills' question gates, not permissions.
- Proposing one blanket "stop asking questions" fix: high free-text gates lose
  real signal — those need batching, not silencing.
- Editing plugin-cache skills and calling it durable.
- Trusting wait totals without the cap: one overnight answer dominates the sum.
