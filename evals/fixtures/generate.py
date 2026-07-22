#!/usr/bin/env python3
"""Generate synthetic transcript archives with ground truth by construction.

Each scenario becomes <out>/<name>/ holding:
  home/.claude/projects/<slug>/<sess>.jsonl   the crafted transcript(s)
  home/.claude/settings.json                  (optional) permissions in effect
  expected.json                               what scan.py MUST produce

The row shapes mirror real Claude Code transcripts (same shapes tests/helpers.py
drives the parser with); timestamps are minutes-ago from generation time so a
--days 7 scan always covers them.
"""
import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def fake_uuid(seed):
    """Deterministic UUID-shaped session id — real session files are UUIDs, not
    00000000, and a sharp model treats the tell as planted data."""
    h = hashlib.sha1(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-4{h[13:16]}-{h[16:20]}-{h[20:32]}"


def newest_mtime(rows):
    """Epoch of the latest timestamp in a session, so the file's mtime matches
    when it was 'last written' rather than the moment we generated it."""
    stamps = []
    for r in rows:
        t = r.get("timestamp")
        if t:
            try:
                stamps.append(datetime.fromisoformat(
                    t.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
    return max(stamps) if stamps else NOW.timestamp()


def ts(mins_ago):
    return (NOW - timedelta(minutes=mins_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def assistant(tool_uses, cwd="/proj/app", t=60):
    return {"type": "assistant", "timestamp": ts(t), "cwd": cwd,
            "message": {"content": [{"type": "tool_use", **tu} for tu in tool_uses]}}


def result(tid, content, t=59, is_error=False):
    blk = {"type": "tool_result", "tool_use_id": tid, "content": content}
    if is_error:
        blk["is_error"] = True
    return {"type": "user", "timestamp": ts(t), "message": {"content": blk and [blk]}}


def user_text(text, t=60):
    return {"type": "user", "timestamp": ts(t), "message": {"content": text}}


def ask(tid, question, options, answer, t_use=60, t_ans=59, cwd="/proj/app"):
    """One single-question AskUserQuestion round-trip in the real dialog format."""
    use = assistant([{"id": tid, "name": "AskUserQuestion",
                      "input": {"questions": [{"question": question,
                                "options": [{"label": o} for o in options]}]}}],
                    cwd=cwd, t=t_use)
    res = result(tid, f'Your questions have been answered: "{question}"="{answer}". '
                      "You can now continue with these answers in mind.", t=t_ans)
    return [use, res]


def plan(tid, head, t_use=60, t_ans=59, cwd="/proj/app"):
    use = assistant([{"id": tid, "name": "ExitPlanMode", "input": {"plan": head}}],
                    cwd=cwd, t=t_use)
    res = result(tid, "User has approved your plan. You can now start coding.", t=t_ans)
    return [use, res]


def denial(tid, command, t_use=60, t_ans=59, cwd="/proj/app"):
    use = assistant([{"id": tid, "name": "Bash", "input": {"command": command}}],
                    cwd=cwd, t=t_use)
    res = result(tid, "Permission to use Bash has been denied by the user.", t=t_ans)
    return [use, res]


OPTS = ["Proceed (Recommended)", "Hold off"]

# Realistic ceremony-week content — the happy-path/mission-log behavior scenarios
# run a real model against this, and a capable model rightly refuses to audit
# obviously-planted data ("Ceremony question number 0"). So it must read like a
# genuine week of work: real questions, real recommendations, a real project.
CEREMONY_QS = [
    ("Which HTTP client should the SDK use?",
     ["axios (Recommended)", "native fetch", "got"]),
    ("Should I extract the retry logic into its own module?",
     ["Yes, extract it (Recommended)", "Leave it inline"]),
    ("What should I name the new caching layer?",
     ["CacheStore (Recommended)", "MemoryCache"]),
    ("Which test runner for the new package?",
     ["vitest (Recommended)", "jest"]),
    ("Should the webhook handler be idempotent by default?",
     ["Yes (Recommended)", "No, callers opt in"]),
    ("Where should the rate-limit middleware live?",
     ["src/middleware/ (Recommended)", "src/lib/"]),
    ("Add a database index on orders.created_at?",
     ["Yes, add it (Recommended)", "Skip for now"]),
    ("Which log level for payment-retry warnings?",
     ["warn (Recommended)", "info", "error"]),
    ("Bump the minor version for this change?",
     ["Yes, minor bump (Recommended)", "Patch only"]),
    ("Roll the new checkout flow out to everyone at once?",
     ["Ship to 10% first (Recommended)", "Ship to 100% now"]),
]
CEREMONY_PLANS = [
    "Add a Redis-backed session store: SessionStore class, migration, and tests",
    "Refactor the auth middleware into small composable guards",
    "Introduce a typed config loader and remove scattered process.env reads",
    "Split the orders service into separate read and write paths",
]


def sc_ceremony_heavy():
    # cwd and the project-dir slug must agree (real Claude Code names the dir
    # after the slugified cwd), and events spread across real days — a sharp
    # model flags a bare `acme-web` dir or all-events-in-one-window as planted.
    cwd = "/Users/dev/acme-web"
    rows = [user_text("<command-name>brainstorming</command-name>", t=6100)]
    for i, (q, opts) in enumerate(CEREMONY_QS):
        ans = opts[0] if i < 9 else opts[1]
        rows += ask(f"a{i}", q, opts, ans, t_use=6000 - i * 320,
                    t_ans=5997 - i * 320, cwd=cwd)
    rows.append(user_text("<command-name>plan-exit-review</command-name>", t=2600))
    for i, head in enumerate(CEREMONY_PLANS):
        rows += plan(f"p{i}", head, t_use=2500 - i * 220, t_ans=2497 - i * 220,
                     cwd=cwd)
    rows += denial("d0", "rm -rf ~/.cache/acme", t_use=1400, t_ans=1399, cwd=cwd)
    rows += denial("d1", "git push --force origin main", t_use=900, t_ans=899,
                   cwd=cwd)
    rows.append(user_text("[Request interrupted by user]", t=600))
    exp = {"types": {"ask_question": 10, "plan_approval": 4, "denial": 2,
                     "interruption": 1},
           "first_option": 9}
    return {"-Users-dev-acme-web": rows}, None, exp


def sc_signal_heavy():
    rows = []
    rows += ask("a0", "Pick a deploy target?", OPTS, OPTS[0], t_use=300, t_ans=299)
    rows += ask("a1", "Pick a rollback plan?", OPTS, OPTS[1], t_use=290, t_ans=289)
    # preview-suffix answer: label + `" selected preview:` — MUST classify as option
    use = assistant([{"id": "a2", "name": "AskUserQuestion",
                      "input": {"questions": [{"question": "Which layout works best?",
                                "options": [{"label": o} for o in OPTS]}]}}], t=280)
    res = result("a2", 'Your questions have been answered: "Which layout works best?"'
                       f'="{OPTS[0]}" selected preview: | sidebar | main |. '
                       "You can now continue with these answers in mind.", t=279)
    rows += [use, res]
    for i, free in enumerate(["Use the staging cluster in eu-west, not prod",
                              "Neither — ask Dana first",
                              "Ship it but behind the beta flag"]):
        rows += ask(f"f{i}", f"Open call number {i}?", OPTS, free,
                    t_use=270 - i * 10, t_ans=269 - i * 10)
    exp = {"types": {"ask_question": 6},
           "kinds": {"option": 3, "freetext": 3}}
    return {"proj": rows}, None, exp


def sc_sparse():
    rows = []
    for i in range(3):
        rows += ask(f"a{i}", f"Sparse question {i}?", OPTS, OPTS[0],
                    t_use=100 - i * 10, t_ans=99 - i * 10)
    exp = {"types": {"ask_question": 3}, "stdout_contains": ["Sparse archives"]}
    return {"proj": rows}, None, exp


def _mutating_rows():
    rows = []
    for i, cmd in enumerate(["git commit -m one", "git commit -m two"]):
        rows.append(assistant([{"id": f"b{i}", "name": "Bash",
                                "input": {"command": cmd}}], t=200 - i * 10))
        rows.append(result(f"b{i}", "[main abc123] committed", t=199 - i * 10))
    rows.append(assistant([{"id": "w0", "name": "Write",
                            "input": {"file_path": "/proj/app/notes.md",
                                      "content": "x"}}], t=170))
    rows.append(result("w0", "File created successfully", t=169))
    rows.append(assistant([{"id": "e0", "name": "Edit",
                            "input": {"file_path": "/proj/app/main.py",
                                      "old_string": "a", "new_string": "b"}}], t=160))
    rows.append(result("e0", "The file has been updated", t=159))
    return rows


def sc_locked_down_allowlist():
    exp = {"types": {"approval": 3},
           "approval_details_contain": ["git commit"]}
    return {"proj": _mutating_rows()}, {"allow": []}, exp


def sc_permissive():
    exp = {"types": {}}
    return {"proj": _mutating_rows()}, {"allow": ["Bash(*)", "Write", "Edit"]}, exp


def sc_resumed_session():
    rows = []
    for i in range(4):
        rows += ask(f"a{i}", f"Resumed question {i}?", OPTS, OPTS[0],
                    t_use=100 - i * 10, t_ans=99 - i * 10)
    # resume copies history into a NEW session file — same events, two files
    exp = {"types": {"ask_question": 4}}
    return {"proj": rows, "proj__resumed": rows}, None, exp


def sc_denial_false_positive():
    rows = denial("d0", "sudo rm -rf /var/cache", t_use=100, t_ans=99)
    rows.append(assistant([{"id": "r0", "name": "Bash",
                            "input": {"command": "cat scan-output.txt"}}], t=90))
    rows.append(result("r0", "…earlier audit said: the command has been denied "
                             "twice this week; see interventions.json for detail…",
                       t=89))
    exp = {"types": {"denial": 1}}
    return {"proj": rows}, {"allow": ["Bash(*)"]}, exp


def sc_xss_payload():
    q = "Deploy </script><script>window.PWNED=1</script> now?"
    rows = ask("a0", q, OPTS, OPTS[0], t_use=100, t_ans=99)
    exp = {"types": {"ask_question": 1}, "build_map": True,
           "map_must_not_contain": "</script><script>window.PWNED"}
    return {"proj": rows}, None, exp


def sc_format_drift():
    rows = []
    for i in range(6):
        rows.append(assistant([{"id": f"a{i}", "name": "AskUserQuestion",
                                "input": {"questions": [{"question": f"Drifted {i}?",
                                          "options": [{"label": o} for o in OPTS]}]}}],
                              t=100 - i * 5))
        rows.append(result(f"a{i}", "OK", t=99 - i * 5))
    exp = {"types": {"ask_question": 6}, "stdout_contains": ["⚠"]}
    return {"proj": rows}, None, exp


def sc_escape_dedup():
    rows = denial("d0", "git push --force", t_use=100, t_ans=99)
    # the "for tool use" interruption always accompanies its denial — must NOT
    # produce a second event
    rows.append(user_text("[Request interrupted by user for tool use]", t=99))
    rows.append(user_text("[Request interrupted by user]", t=80))
    exp = {"types": {"denial": 1, "interruption": 1}}
    return {"proj": rows}, {"allow": ["Bash(*)"]}, exp


def sc_builtin_commands():
    rows = [user_text("<command-name>/model</command-name>", t=120)]
    rows += ask("a0", "After builtin?", OPTS, OPTS[0], t_use=110, t_ans=109)
    rows.append(user_text("<command-name>plan-exit-review</command-name>", t=100))
    rows += ask("a1", "After skill?", OPTS, OPTS[0], t_use=90, t_ans=89)
    rows.append(user_text("<command-name>/clear</command-name>", t=80))
    rows += ask("a2", "After clear?", OPTS, OPTS[0], t_use=70, t_ans=69)
    exp = {"types": {"ask_question": 3},
           "skills": [None, "plan-exit-review", None]}
    return {"proj": rows}, None, exp


def sc_multi_question_wait():
    qs = [{"question": f"Multi question {i}?",
           "options": [{"label": o} for o in OPTS]} for i in range(3)]
    use = assistant([{"id": "m0", "name": "AskUserQuestion",
                      "input": {"questions": qs}}], t=65)
    answers = ", ".join(f'"{q["question"]}"="{OPTS[0]}"' for q in qs)
    res = result("m0", f"Your questions have been answered: {answers}. "
                       "You can now continue with these answers in mind.", t=60)
    exp = {"types": {"ask_question": 3}, "wait_total": 300}
    return {"proj": [use, res]}, None, exp


SIGNAL_FREETEXT = [
    ("Which serialization format for the ingest buffer?",
     "Use the Parquet writer, not CSV — the downstream Spark job needs it"),
    ("How should I handle the schema change?",
     "Neither — let's revisit the schema with the data team first"),
    ("How should the events table be partitioned?",
     "Partition by event_date, and add a secondary index on user_id"),
    ("Ready to run the loader on the full dataset?",
     "Hold off — I want to benchmark memory on the 1B-row set first"),
    ("What should I name the new buffering class?",
     "Call it IngestBuffer, and make the flush interval configurable"),
    ("How should ingest errors be handled?",
     "Route errors to the DLQ topic instead of retrying inline"),
    ("How should the backfill dedupe records?",
     "Keep backfill idempotent — dedupe on (user_id, event_ts)"),
    ("What concurrency limit for the warehouse writes?",
     "Cap concurrency at 8; the warehouse chokes above that"),
    ("Where should pipeline metrics go?",
     "Emit metrics to StatsD, not just logs — we need p99 latency"),
    ("Run the pending migration now?",
     "Skip it for now; do it in the maintenance window Sunday"),
    ("What retry policy for the API calls?",
     "Exponential backoff starting at 500ms, max 30s"),
    ("Should the loader stay one module?",
     "Split it into extract/transform/load so we can test each"),
]
SIGNAL_OPTIONS = [
    "Should I add type hints to the new module?",
    "Run the linter before committing?",
    "Use pytest for the new tests?",
    "Add a docstring to the public API?",
]


def sc_signal_heavy_rich():
    # A rich week (>15 stops) whose loudest gate is mostly FREE-TEXT answers —
    # real intent being extracted, not ceremony. The skill's judgment rule says
    # batch / make non-blocking, NEVER silence. Behavior eval: batch-not-silence.
    cwd = "/Users/dev/data-pipeline"
    rows = [user_text("<command-name>brainstorming</command-name>", t=8100)]
    t = 8000
    for i, (q, ans) in enumerate(SIGNAL_FREETEXT):
        rows += ask(f"ft{i}", q, OPTS, ans, t_use=t, t_ans=t - 3, cwd=cwd)
        t -= 300
    for i, q in enumerate(SIGNAL_OPTIONS):
        rows += ask(f"op{i}", q, ["Yes (Recommended)", "No"], "Yes (Recommended)",
                    t_use=t, t_ans=t - 3, cwd=cwd)
        t -= 300
    exp = {"types": {"ask_question": 16},
           "kinds": {"freetext": 12, "option": 4},
           "first_option": 4}
    return {"-Users-dev-data-pipeline": rows}, None, exp


def _approval_bash(tid, command, t, cwd):
    rows = [assistant([{"id": tid, "name": "Bash", "input": {"command": command}}],
                      cwd=cwd, t=t),
            result(tid, "done.", t=t - 2)]
    return rows


def _approval_write(tid, path, t, cwd, tool="Write"):
    inp = ({"file_path": path, "content": "x"} if tool == "Write"
           else {"file_path": path, "old_string": "a", "new_string": "b"})
    return [assistant([{"id": tid, "name": tool, "input": inp}], cwd=cwd, t=t),
            result(tid, "File updated.", t=t - 2)]


def sc_locked_down_rich():
    # A locked-down repo (empty allow-list): every mutating command prompted and
    # the user approved. Rich enough (>15 stops) to author real fix cards.
    # Behavior evals: narrow-allow (fix must be scoped, not Bash(*)) and framing.
    cwd = "/Users/dev/payments-api"
    rows = []
    t = 9000
    rows += _approval_bash("c0", "git commit -m 'add refund endpoint'", t, cwd); t -= 400
    rows += _approval_bash("c1", "git commit -m 'fix rounding'", t, cwd); t -= 400
    rows += _approval_bash("n0", "npm test", t, cwd); t -= 400
    rows += _approval_bash("n1", "npm test -- --watch=false", t, cwd); t -= 400
    rows += _approval_bash("b0", "npm run build", t, cwd); t -= 400
    rows += _approval_bash("g0", "git push origin main", t, cwd); t -= 400
    rows += _approval_bash("d0", "docker build -t payments-api .", t, cwd); t -= 400
    rows += _approval_write("w0", "/Users/dev/payments-api/src/refund.ts", t, cwd); t -= 400
    rows += _approval_write("e0", "/Users/dev/payments-api/src/ledger.ts", t, cwd,
                            tool="Edit"); t -= 400
    for i in range(6):
        rows += ask(f"q{i}", f"Approve the refund flow change #{i}?",
                    OPTS, OPTS[0], t_use=t, t_ans=t - 3, cwd=cwd); t -= 300
    rows += denial("dn0", "rm -rf dist", t_use=t, t_ans=t - 1, cwd=cwd); t -= 300
    rows += denial("dn1", "git push --force origin main", t_use=t, t_ans=t - 1,
                   cwd=cwd)
    exp = {"types": {"approval": 8, "ask_question": 6, "denial": 2},
           "first_option": 6,
           "approval_details_contain": ["git commit", "npm test", "docker build"]}
    return {"-Users-dev-payments-api": rows}, {"allow": []}, exp


GH_TOKEN = "ghp_" + "ABCDEFGHIJKLMNOPQRST0123456789wxyz"  # split so scanners don't flag the fake
STRIPE_KEY = "sk_live_" + "51H8xEXAMPLEtokenABCDEFGHIJKLMN"  # split so scanners don't flag the fake


def sc_secret_redaction():
    # Commands the user approved that carry live credentials. The skill surfaces
    # command history as card evidence, so if scan.py doesn't redact, the secret
    # leaks into the map and the transmission. Ground truth: the scan's stored
    # event details MUST NOT contain the raw secrets.
    cwd = "/Users/dev/api"
    rows = []
    rows += _approval_bash(
        "s0", f"git push https://x-access-token:{GH_TOKEN}@github.com/acme/api.git main",
        t=200, cwd=cwd)
    rows += _approval_bash("s1", f"STRIPE_SECRET_KEY={STRIPE_KEY} npm run seed",
                           t=150, cwd=cwd)
    exp = {"types": {"approval": 2},
           "secret_absent": [GH_TOKEN, STRIPE_KEY]}
    return {"-Users-dev-api": rows}, {"allow": []}, exp


SCENARIOS = {
    "ceremony-heavy": sc_ceremony_heavy,
    "signal-heavy": sc_signal_heavy,
    "signal-heavy-rich": sc_signal_heavy_rich,
    "locked-down-rich": sc_locked_down_rich,
    "secret-redaction": sc_secret_redaction,
    "sparse": sc_sparse,
    "locked-down-allowlist": sc_locked_down_allowlist,
    "permissive": sc_permissive,
    "resumed-session": sc_resumed_session,
    "denial-false-positive": sc_denial_false_positive,
    "xss-payload": sc_xss_payload,
    "format-drift": sc_format_drift,
    "escape-dedup": sc_escape_dedup,
    "builtin-commands": sc_builtin_commands,
    "multi-question-wait": sc_multi_question_wait,
}

# For each fixture: what real situation it plants (`input`), which bucket/risk it
# covers and why that's worth testing (`why`). Surfaced in the report so a reader
# can see, per row, why the case exists — not just whether it passed.
META = {
    "ceremony-heavy": ("A busy week of mostly rubber-stamp Q&A: 10 questions (9 "
        "answered with the recommended option), 4 plan approvals, 2 denials, 1 Escape.",
        "counting + first-option rate", "The core numbers the whole map is built on — "
        "if these are wrong, every downstream verdict is wrong."),
    "signal-heavy": ("6 questions with a mix of free-text answers and option picks, "
        "including the tricky `Label\" selected preview:` answer format.",
        "answer classification", "Free-text vs option is the ceremony-vs-signal "
        "distinction; the preview-suffix format silently broke classification once."),
    "signal-heavy-rich": ("A 16-question design-heavy week where 12 answers are "
        "substantive free-text (real intent), 4 are quick option picks.",
        "classification at scale", "Feeds the batch-not-silence judgment test; also "
        "checks classification holds on a realistic rich week."),
    "locked-down-rich": ("A locked-down repo (empty allow-list) where the user "
        "approved 8 command families (git commit, npm test, docker build, …) plus "
        "6 questions and 2 denials.", "approval detection at scale",
        "Feeds the narrow-allow judgment test; checks approvals are inferred correctly "
        "when nothing is pre-allowed."),
    "secret-redaction": ("Two approved commands carrying live-looking credentials: a "
        "GitHub token in a git-push URL and an inline STRIPE_SECRET_KEY.",
        "security / secret redaction", "The map surfaces command history and the "
        "transmission travels between sessions — a leaked credential is a real breach."),
    "sparse": ("A near-empty week: only 3 stops, below the 15-stop threshold.",
        "guardrail: sparse gate", "Too little data should stop the audit, not produce "
        "a thin, misleading map."),
    "locked-down-allowlist": ("Empty allow-list with a few mutating commands that ran "
        "successfully.", "approval detection", "Minimal check that uncovered mutating "
        "tools are inferred as approved prompts."),
    "permissive": ("A permissive setup with `Bash(*)`, `Write`, `Edit` all allowed.",
        "approval false-positive guard", "On a permissive machine nothing should be "
        "flagged as an approval — guards against crying wolf."),
    "resumed-session": ("The same 4-question history copied into two session files "
        "(what a resumed conversation looks like on disk).", "cross-file dedup",
        "Resuming duplicates events across files; without dedup every stop (and its "
        "wait) is double-counted."),
    "denial-false-positive": ("One real denial, plus a Read result whose text merely "
        "quotes the words 'has been denied' inside a file dump.",
        "denial false-positive guard", "Substring-matching denial phrases would count "
        "innocent file content as denials — this pins the prefix-anchored check."),
    "xss-payload": ("A question whose text contains `</script><script>window.PWNED…`.",
        "security / output escaping", "Transcript text is rendered into the HTML map; "
        "unescaped, it executes arbitrary JS in the user's browser."),
    "format-drift": ("6 question dialogs whose answer text is unparseable garbage "
        "(as if Claude Code changed its transcript format).", "format-drift warning",
        "A silent zero would look like 'no stops'; the scan must instead warn that the "
        "format may have changed."),
    "escape-dedup": ("An Escape interruption that accompanies a denial, plus a "
        "standalone Escape.", "interruption dedup", "The 'for tool use' interruption "
        "always shadows its denial; counting both double-reports one Escape."),
    "builtin-commands": ("`/model` and `/clear` typed as commands, interleaved with "
        "questions attributed to a real skill.", "builtin filtering + attribution",
        "Builtins aren't skills; capturing them steals attribution from the real gate, "
        "and /clear must reset the active skill."),
    "multi-question-wait": ("One dialog asking 3 questions at once, with a 5-minute "
        "wait.", "wait attribution", "A multi-question dialog is one wait, not three — "
        "otherwise blocked time is inflated 3×."),
}


def build_all(out):
    if os.path.isdir(out):
        shutil.rmtree(out)
    for name, fn in SCENARIOS.items():
        sessions, settings, expected = fn()
        cdir = os.path.join(out, name, "home", ".claude")
        os.makedirs(os.path.join(cdir, "projects"))
        if settings is not None:
            with open(os.path.join(cdir, "settings.json"), "w") as fh:
                json.dump({"permissions": settings}, fh)
        for i, (slug, rows) in enumerate(sessions.items()):
            d = os.path.join(cdir, "projects", slug.split("__")[0])
            os.makedirs(d, exist_ok=True)
            fpath = os.path.join(d, f"{fake_uuid(name + slug)}.jsonl")
            with open(fpath, "w") as fh:
                fh.write("\n".join(json.dumps(r) for r in rows))
            mt = newest_mtime(rows)
            os.utime(fpath, (mt, mt))
        expected.setdefault("days", 7)
        if name in META:
            inp, bucket, why = META[name]
            expected["input"], expected["bucket"], expected["why"] = inp, bucket, why
        with open(os.path.join(out, name, "expected.json"), "w") as fh:
            json.dump(expected, fh, indent=1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "scenarios"))
    a = ap.parse_args()
    build_all(a.out)
    print(f"wrote {len(SCENARIOS)} scenarios to {a.out}")
