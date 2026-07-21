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
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


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


def ask(tid, question, options, answer, t_use=60, t_ans=59):
    """One single-question AskUserQuestion round-trip in the real dialog format."""
    use = assistant([{"id": tid, "name": "AskUserQuestion",
                      "input": {"questions": [{"question": question,
                                "options": [{"label": o} for o in options]}]}}],
                    t=t_use)
    res = result(tid, f'Your questions have been answered: "{question}"="{answer}". '
                      "You can now continue with these answers in mind.", t=t_ans)
    return [use, res]


def plan(tid, head, t_use=60, t_ans=59):
    use = assistant([{"id": tid, "name": "ExitPlanMode", "input": {"plan": head}}],
                    t=t_use)
    res = result(tid, "User has approved your plan. You can now start coding.", t=t_ans)
    return [use, res]


def denial(tid, command, t_use=60, t_ans=59):
    use = assistant([{"id": tid, "name": "Bash", "input": {"command": command}}],
                    t=t_use)
    res = result(tid, "Permission to use Bash has been denied by the user.", t=t_ans)
    return [use, res]


OPTS = ["Proceed (Recommended)", "Hold off"]


def sc_ceremony_heavy():
    rows = []
    for i in range(10):
        ans = OPTS[0] if i < 9 else OPTS[1]
        rows += ask(f"a{i}", f"Ceremony question number {i}?", OPTS, ans,
                    t_use=300 - i * 10, t_ans=299 - i * 10)
    for i in range(4):
        rows += plan(f"p{i}", f"Plan variant {i}", t_use=200 - i * 5, t_ans=199 - i * 5)
    rows += denial("d0", "rm -rf build", t_use=150, t_ans=149)
    rows += denial("d1", "git push --force", t_use=140, t_ans=139)
    rows.append(user_text("[Request interrupted by user]", t=130))
    exp = {"types": {"ask_question": 10, "plan_approval": 4, "denial": 2,
                     "interruption": 1},
           "first_option": 9}
    return {"proj": rows}, None, exp


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


SCENARIOS = {
    "ceremony-heavy": sc_ceremony_heavy,
    "signal-heavy": sc_signal_heavy,
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
            with open(os.path.join(d, f"{i:08d}.jsonl"), "w") as fh:
                fh.write("\n".join(json.dumps(r) for r in rows))
        expected.setdefault("days", 7)
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
