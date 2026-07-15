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

## Procedure

1. **Scan** (deterministic): `python3 scripts/scan.py --days 7 --out interventions.json`
   — parses `~/.claude/projects/*/*.jsonl`, emits every intervention event with the
   skill in effect, which option the user picked, and `wait_s` (how long Claude sat
   blocked). Default window is 7 days; the user can ask for any `--days N`.

2. **Trace causes.** For each major event cluster, read the actual config:
   - `~/.claude/settings.json` and project `.claude/settings.json` (allow/deny/ask)
   - the SKILL.md of any skill that generated ≥5 dialogs — find the literal lines
     that mandate questions (e.g. "STOP. You MUST call AskUserQuestion")
   - `~/.claude/CLAUDE.md` rules that mandate skills or plan mode
     Distinguish user-owned skills (`~/.claude/skills/…`, patchable) from plugin-cache
     skills (`~/.claude/plugins/cache/…`, overwritten on update → prefer a CLAUDE.md
     override and say so in the card).

3. **Author cards** in `cards.json` (schema documented at the top of
   `scripts/build_page.py`). One card per root cause, ordered by wait-time cost.
   Each card: what happened (with the first-option % as evidence), a `cause` box
   naming the exact file, and 1–2 fix **variants** with real unified-diff hunks.
   Every variant needs a one-line `name` — it becomes the text of the decision the
   user pastes back. Recommendations: never recommend removing destructive-command
   deny rules (present the diff, recommend reject); never allowlist mutating MCP
   tools or arbitrary code execution; mark plugin-cache patches as ephemeral.

4. **Build + publish**:
   `python3 scripts/build_page.py --scan interventions.json --cards cards.json --template assets/template.html --out map.html`
   then publish `map.html` as an artifact. The page has approve/reject stamps per
   fix, a variant chooser, wait-time totals, a per-day rhythm chart, the five
   costliest single stops, per-project intervention rates, and a first-option
   breakdown. Keyboard: J/K move between trials, A approve, R reject, V switch
   variant; the bottom bar shows progress and the waiting time approvals would
   reclaim. `?fresh=1` gives a stateless page for demo recordings; the Reset
   button clears saved decisions (decisions are stored per audit date range).

5. **Apply decisions.** The page's "Transmit decisions" button produces lines like
   `- APPROVE (variant A): <name> [fix-1A]` (block header: "Padawan-No-More decisions"). When the user pastes that block,
   apply exactly the approved diffs (they're on the map, verbatim), skip rejected
   and undecided ones, and confirm each file touched.

## Configuration

- `--days N` — audit window (default 7)
- `--cap SECONDS` on build_page.py — wait time above this counts as a walk-away
  and is capped in totals (default 1800)

## Common mistakes

- Counting only permission prompts: on permissive setups (`Bash(*)` allowed),
  ~80% of interventions come from skills' question gates, not permissions.
- Proposing one blanket "stop asking questions" fix: high free-text gates lose
  real signal — those need batching, not silencing.
- Editing plugin-cache skills and calling it durable.
- Trusting wait totals without the cap: one overnight answer dominates the sum.
