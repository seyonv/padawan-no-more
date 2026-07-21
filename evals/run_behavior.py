#!/usr/bin/env python3
"""Behavior evals: run the skill end to end via `claude -p` in a sandbox HOME,
score with deterministic checks + an LLM judge, log to Braintrust (beh-<sha>).

  evals/.venv/bin/python evals/run_behavior.py                    all scenarios
  evals/.venv/bin/python evals/run_behavior.py --only sparse-gate one
  ... --local                                                     skip Braintrust
"""
import argparse
import json
import os
import re
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


def true_stop_count(fixture):
    """Run scan.py ourselves on the pristine fixture; parse 'stops found N'."""
    home = os.path.join(FIXTURES, fixture, "home")
    out = os.path.join(home, "..", "iv-truth.json")
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
        n, _ = true_stop_count(sc["fixture"])
        claims = [int(x) for x in re.findall(r"(\d+)\s+stops", r["stdout"])]
        ok = bool(claims) and all(c == n for c in claims)
        res["stops_match_scan"] = (ok, f"true={n} claimed={claims}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--local", action="store_true")
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
    rows = []
    for sc in scenarios:
        print(f"▸ {sc['name']} ...", flush=True)
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
            _, scan_out = true_stop_count(sc["fixture"])
            transcript += f"\n\nREAL SCAN OUTPUT:\n{scan_out}"
        j = judge(sc["judge"], transcript)
        frac = (sum(1 for ok, _ in checks.values() if ok) / len(checks)) if checks else 1.0
        d = os.path.join(runs_dir, sc["name"])
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "stdout.txt"), "w").write(r["stdout"])
        open(os.path.join(d, "stderr.txt"), "w").write(r["stderr"])
        json.dump({"checks": {k: {"ok": ok, "detail": det} for k, (ok, det) in checks.items()},
                   "judge": j, "exit_code": r["code"]},
                  open(os.path.join(d, "result.json"), "w"), indent=1)
        rows.append({"name": sc["name"], "checks": checks, "judge": j,
                     "checks_frac": frac, "stdout": r["stdout"]})
        status = "PASS" if frac == 1.0 and j["pass"] else "FAIL"
        print(f"  {status}  checks={frac:.2f} judge={'pass' if j['pass'] else 'FAIL'}"
              f"  ({j['reason'][:120]})")
        for k, (ok, det) in checks.items():
            if not ok:
                print(f"     ✗ {k}: {det}")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip() or "nogit"
    os.makedirs(os.path.join(ROOT, "evals", "results"), exist_ok=True)
    json.dump([{k: v for k, v in r.items() if k != "checks"} | {
                  "checks": {ck: {"ok": ok, "detail": det}
                             for ck, (ok, det) in r["checks"].items()}}
               for r in rows],
              open(os.path.join(ROOT, f"evals/results/beh-{sha}.json"), "w"), indent=1)
    if not a.local:
        import braintrust
        exp = braintrust.init(project="padawan-no-more", experiment=f"beh-{sha}",
                              update=True)
        for r in rows:
            exp.log(input=r["name"], output=r["stdout"][-4000:],
                    scores={"checks": r["checks_frac"],
                            "judge": 1 if r["judge"]["pass"] else 0},
                    metadata={"scenario": r["name"], "sha": sha,
                              "judge_reason": r["judge"]["reason"],
                              "check_details": {k: d for k, (ok, d) in r["checks"].items()}})
        print(exp.summarize())
    ok = all(r["checks_frac"] == 1.0 and r["judge"]["pass"] for r in rows)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
