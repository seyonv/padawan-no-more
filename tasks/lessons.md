## 2026-07-16 — Shipped skill improvements that never reached the user

The skill registered in Claude Code was a stale COPY at ~/.claude/skills/padawan-no-more,
so two days of SKILL.md/template changes in this repo never affected real runs.
Rule: after changing any skill in this repo, verify where the installed skill
resolves from (`ls -la ~/.claude/skills/`). It is now a symlink to this repo —
never recreate it as a copy. If a user says "the skill isn't doing X" after X
was implemented, check for a stale installed copy FIRST.
