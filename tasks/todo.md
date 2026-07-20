# Deep-dive validation & hardening — 2026-07-20

Goal: adversarially test padawan-no-more end to end (parser correctness, page
robustness, SKILL.md prompt behavior, fresh-user experience), then fix what breaks.

- [ ] 1. scan.py correctness audit against real transcripts (false denials from
      results merely containing "has been denied"; sidechain events; wait_s
      inflation across resume/compaction; answer-extraction spot checks;
      ExitPlanMode heuristic; interruption double counting)
- [ ] 2. build_page.py + template robustness (</script> injection via transcript
      text; empty/odd schema; cap math consistency)
- [ ] 3. SKILL.md prompt adversarial tests (malicious transmission block;
      demo-mode integrity; sparse-scan flow; "never fake a number")
- [ ] 4. Fresh-eyes user review (output littering / cwd ambiguity; open(1) is
      macOS-only; triggering; install paths)
- [ ] 5. Triage findings, fix, verify
- [ ] 6. Review section below

## Review

(pending)

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

# Self-contained transmission + live self-reloading page — 2026-07-16

- [x] Transmission embeds full unified diffs + file paths (works in any session)
- [x] Assembling page self-reloads every 3.5s; stops at --state complete
- [x] Scanning state: "tracing each cause" placeholder, pulsing live dot
- [x] SKILL.md: local-first flow — open map.html seconds after scan, rebuild per card, artifact optional at end
- [x] Verified: scanning→authoring→complete transitions live-update an open tab; transmission text carries verbatim diffs

# Launch P0s — 2026-07-18

- [x] Verdict share card: canvas→PNG on knighted state (stops, wait, first-option %, reclaimed, mascot, install line)
- [x] Demo mode: examples/interventions.example.json (102 events, 5-trial cards.example.json), build_page --demo chip, scan.py sparse-archives hint
- [x] Marketplace manifests: .claude-plugin/plugin.json + marketplace.json (root SKILL.md works for clone, plugin, and npx skills add)
- [x] SKILL.md: share-card note, demo-mode section, --demo flag doc
- [x] README: install moved above How-it-works, npx/plugin/clone install paths, share-card + training-simulation notes
- [x] Publish prep: GitHub handle (seyonv) filled into README, .claude-plugin/\*.json, and the INSTALL const in assets/template.html

## Review

Verified in headless Chromium against the training-simulation dataset
(102 events, 5 trials), zero console errors:

- Deciding all five trials (4 approve, 1 reject) knights the mascot and
  reveals "Share the verdict" in the bottom bar; hidden until then.
- Card canvas (2400×1350, drawn at 2x): "My Claude stopped to ask me 102
  times.", "4h 15m spent waiting", "68% took the option it recommended",
  "Knighted — 4 fixes approved, ≈ 3h 38m a week reclaimed.", knighted
  mascot (blade lit, braid gone), install line. toDataURL export confirmed
  untainted (1.7 MB PNG). Caught + fixed: local canvas const W shadowed
  DATA.wait's W, blanking the wait line.
- --demo renders the "training simulation — example data" chip; absent on
  normal builds.
