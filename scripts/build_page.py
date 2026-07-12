#!/usr/bin/env python3
"""Build the Need-Me-Less map page from scan output + authored fix cards.

Usage:
  python3 build_page.py --scan interventions.json --cards cards.json \
      --template ../assets/template.html --out map.html

cards.json schema (authored by Claude per audit):
{
  "meta": {"range": "Jul 5 – 12, 2026"},
  "cards": [{
     "id": "fix-1", "title": "...", "rec": ["rec-yes|rec-no|rec-care", "label"],
     "body": "<p>…</p><div class=\"cause\">…</div>",
     "rowlabel": "plan-exit-review dialogs",
     "count": "50 dialogs",                # optional; defaults to "<n> events"
     "filter": {"type": "ask_question", "skill": "plan-exit-review"},
       # filter keys: type / types[], skill (str|list), skill_not[], include_rejected(bool)
     "variants": [{"k":"A","label":"…","star":true,
                   "name":"one-line description used in the copied decisions block",
                   "diff":{"file":"…","note":"…",
                           "hunks":[{"h":"@@ … @@","lines":[["ctx|add|del","text"],…]}]}}]
  }],
  "info": {"title":"…","count":"…","body":"<p>…</p>",
           "rowlabel":"interruptions","filter":{"types":["interruption","ask_rejected"]}}
}
"""
import json, argparse, statistics
from collections import Counter, defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--scan", required=True)
ap.add_argument("--cards", required=True)
ap.add_argument("--template", required=True)
ap.add_argument("--out", default="map.html")
ap.add_argument("--cap", type=int, default=1800, help="walk-away cap in seconds")
args = ap.parse_args()

d = json.load(open(args.scan))
authored = json.load(open(args.cards))
ev, ss = d["events"], d["sessions"]
CAP = args.cap

def selkey(e):
    if e.get("selected_rank") == 0: return "first"
    if e.get("selected_rank") is not None: return "other"
    return "freetext" if e.get("kind") == "freetext" else "unanswered"

def evrow(e):
    r = {"project": e["project"], "session": e["session"], "skill": e.get("skill"),
         "w": round(min(e["wait_s"], CAP)) if e.get("wait_s") else None,
         "wraw": round(e["wait_s"]) if e.get("wait_s") else None}
    t = e["type"]
    if t == "ask_question": r.update(q=e["question"], a=e["selected"], k=selkey(e))
    elif t == "denial": r.update(q=e.get("detail", ""), a="DENIED", k="denied")
    elif t == "plan_approval": r.update(q=e.get("plan_head", ""), a=e["outcome"], k=e["outcome"])
    elif t == "interruption": r.update(q=e.get("detail", "")[:120], a="interrupted", k="interrupted")
    elif t == "ask_rejected": r.update(q=(e.get("questions") or [""])[0], a="dialog dismissed", k="dismissed")
    return r

def matches(e, flt):
    if not flt: return False
    types = flt.get("types") or ([flt["type"]] if flt.get("type") else None)
    if types and e["type"] not in types: return False
    sk = flt.get("skill")
    if sk is not None:
        sks = sk if isinstance(sk, list) else [sk]
        if e.get("skill") not in sks: return False
    if flt.get("skill_not") and e.get("skill") in flt["skill_not"]: return False
    return True

# ---- aggregates ----
byproj = defaultdict(lambda: {"n": 0, "i": 0, "wait": 0.0})
for s in ss:
    byproj[s["project"]]["n"] += 1
    if s["interventions"] > 0: byproj[s["project"]]["i"] += 1
for e in ev:
    if e.get("wait_s"): byproj[e["project"]]["wait"] += min(e["wait_s"], CAP)
projects = sorted([{"name": p, "n": v["n"], "i": v["i"], "pct": round(100 * v["i"] / v["n"]),
                    "wait": round(v["wait"])} for p, v in byproj.items()],
                  key=lambda x: (-x["pct"], -x["n"]))

qs = [e for e in ev if e["type"] == "ask_question"]
overall = Counter(selkey(e) for e in qs)
bysk, skwait = defaultdict(Counter), Counter()
for e in qs: bysk[e.get("skill") or "(direct model question)"][selkey(e)] += 1
for e in ev:
    if e.get("wait_s"): skwait[e.get("skill") or "(direct model question)"] += min(e["wait_s"], CAP)
skillrows = sorted([{"skill": k, **{c: v.get(c, 0) for c in ("first", "other", "freetext", "unanswered")},
                     "total": sum(v.values()), "wait": round(skwait.get(k, 0))}
                    for k, v in bysk.items()], key=lambda x: -x["total"])

waits = sorted(e["wait_s"] for e in ev if e.get("wait_s"))
wait = {"total": round(sum(waits)), "capped": round(sum(min(w, CAP) for w in waits)),
        "median": round(statistics.median(waits)) if waits else 0,
        "max": round(waits[-1]) if waits else 0, "n": len(waits),
        "over_cap": sum(1 for w in waits if w > CAP), "cap": CAP}

plans = [e for e in ev if e["type"] == "plan_approval"]

# ---- resolve authored cards ----
cards = []
for c in authored.get("cards", []):
    rows = [evrow(e) for e in ev if matches(e, c.get("filter"))]
    c = dict(c)
    c["rows"] = rows
    c.setdefault("count", f"{len(rows)} events")
    c["wait"] = round(sum(r["w"] or 0 for r in rows)) or None
    c.pop("filter", None)
    cards.append(c)
info = authored.get("info")
if info:
    info = dict(info)
    info["rows"] = [evrow(e) for e in ev if matches(e, info.get("filter"))]
    info.setdefault("count", f"{len(info['rows'])} events")
    info.pop("filter", None)

DATA = {"meta": authored.get("meta", {"range": ""}), "projects": projects,
        "overall": dict(overall), "skillrows": skillrows, "wait": wait,
        "cards": cards, "info": info,
        "totals": {"events": len(ev), "sessions": len(ss),
                   "sessions_hit": sum(1 for s in ss if s["interventions"] > 0),
                   "questions": len(qs), "plans": len(plans),
                   "plans_approved": sum(1 for e in plans if e["outcome"] == "approved")}}

out = open(args.template).read().replace("/*__DATA__*/", "const DATA = " + json.dumps(DATA) + ";")
open(args.out, "w").write(out)
print(f"wrote {args.out} ({len(out)} bytes) — {len(cards)} cards, {len(ev)} events")
