#!/usr/bin/env python3
"""Run scan.py/build_page.py against generated fixtures; score vs expected.json.

  python3 evals/run_deterministic.py --local        offline asserts, exit code
  evals/.venv/bin/python evals/run_deterministic.py + Braintrust experiment det-<sha>
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "scripts", "scan.py")
BUILD = os.path.join(ROOT, "scripts", "build_page.py")
TEMPLATE = os.path.join(ROOT, "assets", "template.html")


def run_scenario(sdir):
    home = os.path.join(sdir, "home")
    exp = json.load(open(os.path.join(sdir, "expected.json")))
    out = tempfile.mktemp(suffix=".json")
    p = subprocess.run([sys.executable, SCAN, "--days", str(exp.get("days", 7)),
                        "--out", out], env=dict(os.environ, HOME=home),
                       capture_output=True, text=True, check=True)
    ev = json.load(open(out))["events"]
    o = {"counts": {}, "stdout": p.stdout, "map_html": None}
    for e in ev:
        o["counts"][e["type"]] = o["counts"].get(e["type"], 0) + 1
    asks = [e for e in ev if e["type"] == "ask_question"]
    o["first_option"] = sum(1 for e in asks if e.get("selected_rank") == 0)
    o["kinds"] = {}
    for e in asks:
        if e.get("kind") != "unanswered":
            o["kinds"][e["kind"]] = o["kinds"].get(e["kind"], 0) + 1
    o["wait_total"] = sum(e["wait_s"] for e in ev if e.get("wait_s"))
    o["skills"] = [e.get("skill") for e in asks]
    o["approval_details"] = [e.get("detail", "") for e in ev if e["type"] == "approval"]
    # everything the scan stored that could carry a leaked secret, incl. what
    # build_page.py renders into card evidence
    o["details_blob"] = " ".join(
        str(e.get(k, "")) for e in ev
        for k in ("detail", "command", "result", "plan_head", "selected", "question"))
    if exp.get("build_map"):
        cards = tempfile.mktemp(suffix=".json")
        mh = tempfile.mktemp(suffix=".html")
        json.dump({"meta": {"range": "eval"}, "cards": []}, open(cards, "w"))
        subprocess.run([sys.executable, BUILD, "--scan", out, "--cards", cards,
                        "--template", TEMPLATE, "--state", "complete", "--out", mh],
                       capture_output=True, text=True, check=True)
        o["map_html"] = open(mh).read()
    return o, exp


def score(o, exp):
    s = {}

    def add(key, ok, detail):
        s[key] = {"score": 1 if ok else 0, "detail": detail}

    if "types" in exp:
        add("types", o["counts"] == exp["types"],
            f"got {o['counts']} want {exp['types']}")
    if "first_option" in exp:
        add("first_option", o["first_option"] == exp["first_option"],
            f"got {o['first_option']} want {exp['first_option']}")
    if "kinds" in exp:
        add("kinds", o["kinds"] == exp["kinds"], f"got {o['kinds']} want {exp['kinds']}")
    if "wait_total" in exp:
        add("wait_total", abs(o["wait_total"] - exp["wait_total"]) <= 1,
            f"got {o['wait_total']} want {exp['wait_total']}")
    if "skills" in exp:
        add("skills", o["skills"] == exp["skills"],
            f"got {o['skills']} want {exp['skills']}")
    if "approval_details_contain" in exp:
        misses = [n for n in exp["approval_details_contain"]
                  if not any(n in d for d in o["approval_details"])]
        add("approval_details", not misses,
            f"missing {misses} in {o['approval_details']}")
    for needle in exp.get("stdout_contains", []):
        add(f"stdout has {needle[:20]!r}", needle in o["stdout"], "scan stdout check")
    for needle in exp.get("stdout_not_contains", []):
        add(f"stdout lacks {needle[:20]!r}", needle not in o["stdout"],
            "scan stdout check")
    if "map_must_not_contain" in exp:
        add("map_escaped", o["map_html"] is not None
            and exp["map_must_not_contain"] not in o["map_html"],
            f"payload {exp['map_must_not_contain']!r} must not survive into map.html")
    for secret in exp.get("secret_absent", []):
        leaked = secret in o["details_blob"]
        add(f"secret_absent {secret[:12]}…", not leaked,
            "LEAKED into scan event details" if leaked else "redacted")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true",
                    help="plain asserts, no Braintrust upload")
    ap.add_argument("--scenarios",
                    default=os.path.join(ROOT, "evals", "fixtures", "scenarios"))
    a = ap.parse_args()
    subprocess.run([sys.executable, os.path.join(ROOT, "evals/fixtures/generate.py"),
                    "--out", a.scenarios], check=True, capture_output=True)
    rows = []
    for name in sorted(os.listdir(a.scenarios)):
        out, exp = run_scenario(os.path.join(a.scenarios, name))
        scores = score(out, exp)
        rows.append({"name": name, "scores": scores})
        flat = {k: v["score"] for k, v in scores.items()}
        ok = all(flat.values())
        print(("PASS" if ok else "FAIL"), name)
        if not ok:
            for k, v in scores.items():
                if not v["score"]:
                    print(f"     ✗ {k}: {v['detail']}")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=ROOT).stdout.strip() or "nogit"
    os.makedirs(os.path.join(ROOT, "evals", "results"), exist_ok=True)
    json.dump(rows, open(os.path.join(ROOT, f"evals/results/det-{sha}.json"), "w"),
              indent=1)
    try:
        sys.path.insert(0, os.path.join(ROOT, "evals"))
        import report
        print("report →", report.build())
    except Exception as e:
        print(f"(report skipped: {e})")
    all_ok = all(v["score"] for r in rows for v in r["scores"].values())
    if a.local:
        sys.exit(0 if all_ok else 1)
    import braintrust
    exp_h = braintrust.init(project="padawan-no-more", experiment=f"det-{sha}",
                            update=True)
    for r in rows:
        exp_h.log(input=r["name"],
                  output={k: v["detail"] for k, v in r["scores"].items()},
                  scores={k: v["score"] for k, v in r["scores"].items()},
                  metadata={"scenario": r["name"], "sha": sha})
    print(exp_h.summarize())
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
