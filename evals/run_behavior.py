#!/usr/bin/env python3
"""Behavior evals: run the skill end to end via `claude -p` in a sandbox HOME,
score with deterministic checks + an LLM judge, log to Braintrust (beh-<sha>).

  evals/.venv/bin/python evals/run_behavior.py                    all scenarios ×3
  evals/.venv/bin/python evals/run_behavior.py --only sparse-gate --repeat 1
  ... --local                                                     skip Braintrust
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
sys.path.insert(0, os.path.join(ROOT, "evals", "behavior"))
from judges import judge  # noqa: E402
from sandbox import make_sandbox, run_claude  # noqa: E402

SCAN = os.path.join(ROOT, "scripts", "scan.py")
FIXTURES = os.path.join(ROOT, "evals", "fixtures", "scenarios")
MODEL_DEFAULT = os.environ.get("EVAL_MODEL", "haiku")


def scan_home(home):
    """Run scan.py ourselves on a HOME; parse 'stops found N'. Must be the SAME
    sandbox home the model scanned (post-run) — Claude Code writes the current
    audit session into projects/, so a pristine-fixture scan undercounts the
    session logs by one and would flag honest reporting as a discrepancy."""
    out = os.path.join(home, ".claude", "iv-truth.json")
    p = subprocess.run([sys.executable, SCAN, "--days", "7", "--out", out],
                       env=dict(os.environ, HOME=home),
                       capture_output=True, text=True, check=True)
    m = re.search(r"stops found\s+(\d+)", p.stdout)
    return int(m.group(1)), p.stdout


def run_checks(sc, sb, r, settings_before):
    checks = sc.get("checks") or {}
    res = {}
    if checks.get("cwd_clean"):
        left = os.listdir(sb["cwd"])
        res["cwd_clean"] = (not left, f"cwd contents: {left}")
    if checks.get("home_settings_unchanged"):
        path = os.path.join(sb["home"], ".claude", "settings.json")
        after = open(path).read() if os.path.isfile(path) else None
        res["home_settings_unchanged"] = (after == settings_before,
                                          "settings.json modified" if after != settings_before else "unchanged")
    for rx in checks.get("stdout_regex", []):
        res[f"stdout ~ {rx[:24]}"] = (bool(re.search(rx, r["stdout"])),
                                      f"regex {rx!r} in stdout")
    for rx in checks.get("stdout_not_regex", []):
        res[f"stdout !~ {rx[:24]}"] = (not re.search(rx, r["stdout"]),
                                       f"regex {rx!r} absent from stdout")
    if checks.get("stops_match_scan"):
        n, _ = scan_home(sb["home"])
        claims = [int(x) for x in re.findall(r"(\d+)\s+stops", r["stdout"])]
        ok = bool(claims) and all(c == n for c in claims)
        res["stops_match_scan"] = (ok, f"true={n} claimed={claims}")
    return res


def run_once(sc, runs_dir, rep):
    """One run of one scenario → a result dict for rep index `rep`."""
    sb = make_sandbox(sc.get("fixture"))
    settings_before = None
    if sc.get("seed_settings"):
        path = os.path.join(sb["home"], ".claude", "settings.json")
        with open(path, "w") as fh:
            fh.write(sc["seed_settings"])
        settings_before = sc["seed_settings"]
    r = run_claude(sc["prompt"], sb, model=sc.get("model"),
                   timeout=sc.get("timeout", 600))
    checks = run_checks(sc, sb, r, settings_before)
    transcript = r["stdout"]
    if sc.get("checks", {}).get("stops_match_scan"):
        _, scan_out = scan_home(sb["home"])
        transcript += ("\n\nREAL SCAN OUTPUT (same sandbox the model scanned; "
                       "includes the current audit session):\n" + scan_out)
    j = judge(sc["judge"], transcript)
    frac = (sum(1 for ok, _ in checks.values() if ok) / len(checks)) if checks else 1.0
    passed = frac == 1.0 and j["pass"]
    d = os.path.join(runs_dir, sc["name"], f"rep{rep}")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "stdout.txt"), "w").write(r["stdout"])
    open(os.path.join(d, "stderr.txt"), "w").write(r["stderr"])
    rec = {"name": sc["name"], "rep": rep, "model": sc.get("model") or MODEL_DEFAULT,
           "passed": passed, "checks_frac": frac, "judge": j,
           "checks": {k: {"ok": ok, "detail": det} for k, (ok, det) in checks.items()},
           "stdout_tail": r["stdout"][-4000:]}
    json.dump(rec, open(os.path.join(d, "result.json"), "w"), indent=1)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--repeat", type=int, default=3,
                    help="runs per scenario; pass-rate flags flaky (<100%%) scenarios")
    a = ap.parse_args()
    if not os.path.isdir(FIXTURES) or not os.listdir(FIXTURES):
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "evals/fixtures/generate.py"),
                        "--out", FIXTURES], check=True, capture_output=True)
    scenarios = yaml.safe_load(open(os.path.join(ROOT, "evals/behavior/scenarios.yaml")))
    if a.only:
        scenarios = [s for s in scenarios if s["name"] == a.only]
        if not scenarios:
            sys.exit(f"no scenario named {a.only}")
    runs_dir = os.path.join(ROOT, "evals", "behavior", "runs")
    if os.path.isdir(runs_dir):
        shutil.rmtree(runs_dir)
    scenario_rows = []
    for sc in scenarios:
        print(f"▸ {sc['name']}  ({sc.get('model') or MODEL_DEFAULT}) ...", flush=True)
        reps = [run_once(sc, runs_dir, i) for i in range(a.repeat)]
        n_pass = sum(1 for x in reps if x["passed"])
        rate = n_pass / len(reps)
        flaky = 0 < n_pass < len(reps)
        tag = "PASS" if rate == 1.0 else ("FLAKY" if flaky else "FAIL")
        print(f"  {tag}  pass-rate {n_pass}/{len(reps)}")
        for x in reps:
            if not x["passed"]:
                bad = [f"{k}:{v['detail']}" for k, v in x["checks"].items() if not v["ok"]]
                jr = "" if x["judge"]["pass"] else f" judge:{x['judge']['reason'][:110]}"
                print(f"     rep{x['rep']} ✗ {'; '.join(bad)}{jr}")
        scenario_rows.append({"name": sc["name"], "model": sc.get("model") or MODEL_DEFAULT,
                              "pass_rate": rate, "n_pass": n_pass, "n": len(reps),
                              "flaky": flaky, "reps": reps})
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip() or "nogit"
    os.makedirs(os.path.join(ROOT, "evals", "results"), exist_ok=True)
    json.dump({"sha": sha, "kind": "behavior", "repeat": a.repeat,
               "scenarios": scenario_rows},
              open(os.path.join(ROOT, f"evals/results/beh-{sha}.json"), "w"), indent=1)
    if not a.local:
        import braintrust
        exp = braintrust.init(project="padawan-no-more", experiment=f"beh-{sha}",
                              update=True)
        for srow in scenario_rows:
            for x in srow["reps"]:
                exp.log(input=f"{srow['name']}#rep{x['rep']}", output=x["stdout_tail"],
                        scores={"passed": 1 if x["passed"] else 0,
                                "checks": x["checks_frac"],
                                "judge": 1 if x["judge"]["pass"] else 0},
                        metadata={"scenario": srow["name"], "rep": x["rep"],
                                  "model": srow["model"], "sha": sha,
                                  "pass_rate": srow["pass_rate"],
                                  "judge_reason": x["judge"]["reason"]})
        print(exp.summarize())
    all_green = all(s["pass_rate"] == 1.0 for s in scenario_rows)
    sys.exit(0 if all_green else 1)


if __name__ == "__main__":
    main()
