# Iteration log — evals that drove real fixes

This is the teaching artifact: it shows the eval loop actually working — a
behavior we wanted, an eval that **failed** against the shipped code, a fix, and
the eval going **green** and staying that way. Read top-to-bottom to see how
evals turn "the skill feels right" into "the skill is provably right."

The loop, every time:

1. **Name the behavior** you want as a rule.
2. **Write an eval and watch it go RED** against current code. The red is the
   product — it proves the eval has teeth and the gap is real.
3. **Fix** the prompt (SKILL.md) or the tooling (scan.py).
4. **Watch it go GREEN.** Now it's a permanent regression lock.

---

## Iteration 1 — secrets leaking into card evidence (RED → GREEN)

**The behavior we want:** the skill surfaces your command history as evidence in
the Trials, and the transmission block travels between sessions. A credential in
a command (a token in a git-push URL, an inline `STRIPE_SECRET_KEY=…`) must never
be shown or transmitted in the clear.

**Step 1 — eval written, and it FAILED against the shipped scan.py:**

```
$ python3 evals/run_deterministic.py --local
FAIL secret-redaction
     ✗ secret_absent ghp_ABCDEFGH…: LEAKED into scan event details
     ✗ secret_absent sk_live_51H8…: LEAKED into scan event details
```

The fixture (`evals/fixtures/generate.py::sc_secret_redaction`) plants two real-
shaped secrets in approved commands; the scorer asserts the scan's stored event
details never contain them. They did — `scan.py` recorded commands verbatim, so
the secrets would have flowed straight into `cards.json`, `map.html`, and the
copy-paste transmission. Committed as the RED commit (`7501a38`) so the failure
is on the record.

**Step 2 — the fix (`scan.py`):** a pattern-based `_redact()` (GitHub / Stripe /
OpenAI / Slack / AWS tokens, JWTs, `Bearer` headers, in-URL credentials, and
`key=VALUE` assignments) applied to every human-readable field before events are
written. Committed as the GREEN commit (`c79b736`).

**Step 3 — GREEN, and locked:**

```
$ python3 evals/run_deterministic.py --local
PASS secret-redaction        # + the other 14 still green
$ python3 -m unittest discover tests
Ran 33 tests in 0.9s — OK    # 3 new redaction unit tests
```

`diff 7501a38 c79b736` is the whole story in two commits. Any future edit that
re-introduces the leak fails `secret-redaction` immediately.

---

## Iteration 2 & 3 — judgment rules that were ALREADY right (GREEN first try)

Not every eval finds a bug — and that's a real lesson, not a wasted run. Two
scenarios probing SKILL.md's subtler judgment rules passed on the first try:

- **`batch-not-silence`** — given a gate whose answers are mostly free-text
  (real intent), the skill must propose batching / non-blocking, never silencing.
  SKILL.md's core judgment rule already says this clearly, and the skill applied
  it. **Passed first run.**
- **`narrow-allow`** — the fix for approval prompts must be a scoped rule
  (`Bash(git commit *)`), never a blanket `Bash(*)`. Already handled. **Passed
  first run.**

These are now **regression locks**: the prompt is good today, and if a future
edit weakens either rule, the eval turns red. A green-first-try eval isn't
wasted — it converts an implicit "I think the wording covers this" into an
enforced guarantee.

---

## How to run your own iteration

1. Add a fixture in `evals/fixtures/generate.py` (deterministic ground truth) or
   a scenario in `evals/behavior/scenarios.yaml` (end-to-end behavior + rubric).
2. Run it and confirm the RED: `python3 evals/run_deterministic.py --local` or
   `evals/.venv/bin/python evals/run_behavior.py --only <name> --repeat 1`.
3. Fix SKILL.md or the scripts.
4. Re-run to GREEN. Commit the eval and the fix (as a red commit then a green
   commit if you want the diff on the record).
5. `open evals/results/report.html` to see it, and Braintrust to diff runs over
   time.
