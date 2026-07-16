# Sidebar rail + progressive build — 2026-07-15

- [x] template.html: two-column grid, sticky sidebar (mascot, progress, scrollspy nav)
- [x] template.html: delete #floatwan + its JS
- [x] template.html: dissolve duo grid → full-width rhythm strip + costliest list
- [x] template.html: hero band without mascot corner
- [x] template.html: skeleton trial cards + build states (authoring meter, disabled Transmit)
- [x] build_page.py: --state/--total → DATA.build
- [x] SKILL.md: publish-early procedure + mission log v2
- [x] Verify: screenshots at 1440/1280/1024, complete + authoring states
- [x] Regenerate docs/screenshots, commit

## Review

Verified in headless Chromium with the real 134-event dataset, zero console
errors:

- 1440px: sticky rail with mascot/progress/scrollspy nav; no gutter voids —
  the imbalanced duo section is gone (rhythm + costliest are full-width).
- Scrollspy uses a 140px reading line (IntersectionObserver mis-highlights on
  very tall trial cards); section + active trial highlight together.
- Decisions: rail nav gets ✓/✕ per trial, decided-count + reclaimed time
  mirror the bottom bar, mascot levels up (knight state confirmed).
- `--state authoring --total N`: shimmer skeleton trials, saber becomes a
  build meter, Transmit disabled ("Assembling 2/5…"), rail shows
  "⏳ authoring trial 3 of 5", hero notes the map is still assembling.
- 1024px: rail collapses to a horizontal strip (nav + bubble hidden).
- Rail bubble auto-hides under 830px viewport height so nav stays reachable.
