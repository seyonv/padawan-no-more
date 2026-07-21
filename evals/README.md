# Evals

Two suites, both logged to Braintrust project
[`padawan-no-more`](https://www.braintrust.dev/app/sv/p/padawan-no-more)
(experiments `det-<sha>` / `beh-<sha>`), with a local JSON dump in
`evals/results/` either way.

## Setup

```bash
cd evals && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export BRAINTRUST_API_KEY=sk-...   # already in ~/.bash_profile on this machine
```

## Deterministic suite (fast, free — run on every change)

Generates 12 synthetic transcript archives whose correct scan output is known
by construction, runs the real `scripts/scan.py` / `build_page.py` against
them, scores exact-match.

```bash
python3 evals/run_deterministic.py --local        # offline, plain asserts, exit code
evals/.venv/bin/python evals/run_deterministic.py # + log experiment to Braintrust
```

## Behavior suite (token-costing — run on demand)

Runs the skill end to end: sandboxed `$HOME` with a fixture archive and the
skill installed, `claude -p "run the jedi trials"`, then deterministic checks
plus an LLM judge (which also shells out to `claude -p`, so no separate
Anthropic key is needed).

```bash
evals/.venv/bin/python evals/run_behavior.py                    # all scenarios (~10-20 min)
evals/.venv/bin/python evals/run_behavior.py --only sparse-gate # one scenario
```

Env vars: `EVAL_MODEL` (behavior runs, default `haiku`), `EVAL_JUDGE_MODEL`
(judging, default `sonnet`). A scenario may pin its own `model:` in
`scenarios.yaml` — the three apply-gate scenarios use `sonnet` because they test
the step-5 safety-gate _logic_, and on `haiku` whether the skill even loads from
a pasted transmission is non-deterministic (a finding, not a flake — see
`tasks/todo.md`). Raw per-scenario transcripts land in
`evals/behavior/runs/<name>/`.
