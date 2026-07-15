# Sidebar rail layout + progressive build experience

Approved 2026-07-15.

## Problem

1. The map page reserves a right gutter for a floating mascot (`#floatwan`) that
   renders as a small faded starburst drifting in empty space, clipped at some
   scroll positions. Two layout-fix commits haven't tamed it.
2. The "Stops per day / Costliest stops" duo is two columns with wildly
   different natural heights (~350px vs ~900px), leaving a giant white void.
3. Content is locked to ~1000px with dead space to the right of every card.
4. The page is published once at the end of a multi-minute run — the user
   stares at nothing while trials are authored.

## Design

### Layout: sticky sidebar rail

- At ≥1100px, `.wrap` becomes a two-column grid: `260px` sticky sidebar +
  fluid main column (`minmax(0, 1fr)`).
- Sidebar (sticky, top-aligned): wordmark, leveling mascot + rank + speech
  bubble, trials-decided progress (dots + reclaimable wait time), scrollspy
  section nav (Verdict / Answers / Systems / Trials I–N, each trial marked
  with its approve/reject state), keyboard-hint footnote.
- `#floatwan` and its scroll logic are deleted — the sidebar replaces it.
- The `duo` grid is dissolved: rhythm chart becomes a full-width strip;
  costliest stops a full-width list. No height matching → no voids.
- Hero band drops the embedded mascot corner; stat tiles use the full width.
- <1100px: sidebar collapses to a slim horizontal strip under the header
  (small mascot + progress; nav hidden). Bottom decision bar unchanged.

### Progressive build

- `build_page.py` gains `--state scanning|authoring|complete` (default
  `complete`), `--authored K`, `--total N`, injected as `DATA.build`.
- Non-complete state renders: skeleton trial cards with a shimmer/holocron
  pulse ("Trial III is being authored…"), mascot in training pose, bottom bar
  shows a build meter instead of Transmit (Transmit disabled), plus a line
  "still assembling — refresh in a minute" (static page, no polling).
- SKILL.md procedure: publish the artifact immediately after scan+trace with
  `--state authoring --total N`; redeploy the same artifact URL after each
  1–2 cards; final build uses `--state complete`.
- Mission log v2: "Author the trials" phase gets per-trial sub-lines
  (`└─ ✦ Trial I · plan-exit-review · 4h 23m`).

## Files

- `assets/template.html` — grid, sidebar, scrollspy, skeletons, build states,
  floatwan removal.
- `scripts/build_page.py` — state flags → `DATA.build`.
- `SKILL.md` — publish-early procedure + mission log v2.
- `docs/screenshots/*` — regenerate after.

## Non-goals

Dark theme, data schema changes, scan.py changes, artifact polling/live
refresh.
