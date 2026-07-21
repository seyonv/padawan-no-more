# Evals

Two suites that keep padawan-no-more honest: a **deterministic** one that scores
the parser against known-answer fixtures, and a **behavior** one that runs the
whole skill end-to-end and grades what Claude actually does. Both log to
Braintrust project
[`padawan-no-more`](https://www.braintrust.dev/app/sv/p/padawan-no-more)
(experiments `det-<sha>` / `beh-<sha>`) and drop a local JSON dump in
`evals/results/`.

New to evals? Read **[ITERATION-LOG.md](ITERATION-LOG.md)** — it walks a real
red→green fix (a secret-leak bug an eval caught) and shows the loop in action.

## Setup

```bash
cd evals && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export BRAINTRUST_API_KEY=sk-...   # already in ~/.bash_profile on this machine
```

## Deterministic suite (fast, free — run on every change)

15 synthetic transcript archives whose correct scan output is known **by
construction** (the generator writes both the transcript and the expected
answer), scored exact-match against the real `scripts/scan.py` / `build_page.py`.
One scenario per bug class we care about: false-positive denials, resume dedup,
answer classification, XSS escaping, inferred approvals, secret redaction, and
more.

```bash
python3 evals/run_deterministic.py --local        # offline, plain asserts, exit code
evals/.venv/bin/python evals/run_deterministic.py # + log experiment to Braintrust
```

## Behavior suite (token-costing — run on demand)

Runs the skill the way a user does: a sandboxed `$HOME` with a fixture archive
and the skill installed, `claude -p "run the jedi trials"`, then deterministic
checks plus an LLM judge (which also shells out to `claude -p`, so no separate
Anthropic key is needed). Covers the happy path, the sparse gate, demo-mode
integrity, the three apply-gate attacks, mission-log honesty, and two judgment
rules (batch-don't-silence, narrow-allow).

```bash
evals/.venv/bin/python evals/run_behavior.py                       # all scenarios ×3
evals/.venv/bin/python evals/run_behavior.py --only narrow-allow   # one scenario ×3
evals/.venv/bin/python evals/run_behavior.py --only narrow-allow --repeat 1   # quick
```

### Pass-rate (flakiness) — `--repeat N`

LLM behavior is non-deterministic, so a single green can be luck. Each scenario
runs `N` times (default 3) and reports a **pass-rate**; anything between 0 and N
is flagged `FLAKY`. A scenario isn't "passing" until it's `N/N`.

### Model pins

Env: `EVAL_MODEL` (behavior runs, default `haiku`), `EVAL_JUDGE_MODEL` (judging,
default `sonnet`). A scenario may pin its own `model:` in `scenarios.yaml`.
Scenarios that verify **faithful multi-step procedure / rule-following** (full
audit flow, honest numbers, the apply gate, the judgment rules) pin `sonnet`,
because on `haiku` that following is unreliable — a documented finding, not a
flake (see `tasks/todo.md`). The simple **stop-and-report** gates (sparse, demo)
keep the cheap `haiku` default. Raw per-run transcripts land in
`evals/behavior/runs/<name>/rep<i>/`.

## Looking at results

- **Local report:** every run regenerates `evals/results/report.html` — a
  self-contained page (no login) with pass-rate bars, expandable per-run judge
  reasoning, and a per-run trend. `open evals/results/report.html`.
- **Braintrust:** the historical surface — every experiment, per-scenario
  scores, and cross-run diffs (e.g. before/after a SKILL.md edit).

## Iterating — the loop

Want to improve the skill? Drive it with an eval (see ITERATION-LOG.md for a
worked example):

1. Add a fixture (`fixtures/generate.py`) or scenario (`behavior/scenarios.yaml`)
   for the behavior you want.
2. Run it and confirm it's **RED** against today's code.
3. Fix `SKILL.md` or the scripts.
4. Re-run to **GREEN**; commit the eval and the fix. It's now a regression lock.
