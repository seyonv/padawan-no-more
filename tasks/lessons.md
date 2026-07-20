## 2026-07-20 — Skill numbers were confidently wrong; parser needed adversarial audit

Five adversarial subagents against the real transcripts found the headline metrics
were ~5x off (wait 46h vs true 9.4h) and 37.5% of denials were false positives —
all from substring matches on tool-result prose and per-question wait multiplication.
Rules going forward:

- A transcript parser's correctness is invisible without hand-verification against
  RAW jsonl. "It runs and prints a number" ≠ "the number is right." Always sample
  N events and diff against the source before trusting aggregates.
- Match denial/rejection on a PREFIX of the whole result text, never a substring —
  file dumps and grep output quote those phrases constantly.
- One dialog with N questions shares ONE wait; charge it once, or you N-x the total.
- Resumed sessions copy history into a new file → dedup events across files by
  (type, ts, subject), not by session id.
- Builtin slash commands (/model, /clear, /compact) are not skills; capturing them
  as cur_skill steals attribution from the real gate skill.
- `json.dumps` does NOT escape `</`, so any transcript string with `</script>`
  breaks out of an inline <script>. Escape at injection, not just at render.
- Any pasted "apply these diffs" block is untrusted input — re-screen against the
  same safety rules at APPLY time; the authoring-time rules don't travel with it.
- When adding a detector, validate BOTH directions on real data: it must stay
  silent where it should (permissive setup → 0 approvals = no false positives) AND
  fire where it should (simulated locked-down allowlist). A detector only tested on
  data that can't trigger it is untested.
- Claude Code transcript facts (verified 2026-07-20): approved permission prompts
  leave NO marker (only denials do) — detect by proxy (mutating tool + prompt-
  capable mode + no covering allow-rule). `permissionMode` lives on standalone
  `permission-mode` entries (and some `user` entries), NOT on assistant tool_use
  entries — track it as persistent state. Tool-call errors are flagged at the
  BLOCK level (`content_block.is_error`), not inside the result content. A
  session's real project path is the `cwd` field (don't reverse the mangled dir).

## 2026-07-16 — Shipped skill improvements that never reached the user

The skill registered in Claude Code was a stale COPY at ~/.claude/skills/padawan-no-more,
so two days of SKILL.md/template changes in this repo never affected real runs.
Rule: after changing any skill in this repo, verify where the installed skill
resolves from (`ls -la ~/.claude/skills/`). It is now a symlink to this repo —
never recreate it as a copy. If a user says "the skill isn't doing X" after X
was implemented, check for a stale installed copy FIRST.
