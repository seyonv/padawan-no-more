"""Tests for build_page.py — the security escape and the crash guards."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT, BUILD, TEMPLATE


def build(events, sessions, cards, extra_args=()):
    tmp = tempfile.mkdtemp(prefix="pnm-build-")
    scan = os.path.join(tmp, "iv.json")
    cardf = os.path.join(tmp, "cards.json")
    out = os.path.join(tmp, "map.html")
    with open(scan, "w") as fh:
        json.dump({"events": events, "sessions": sessions, "meta": {"days": 7, "files": 1}}, fh)
    with open(cardf, "w") as fh:
        json.dump(cards, fh)
    r = subprocess.run([sys.executable, BUILD, "--scan", scan, "--cards", cardf,
                        "--template", TEMPLATE, "--out", out, *extra_args],
                       capture_output=True, text=True)
    html = ""
    if os.path.exists(out):
        with open(out) as fh:
            html = fh.read()
    return r, html


class TestScriptInjection(unittest.TestCase):
    def test_script_tag_in_transcript_cannot_break_out(self):
        # a question containing </script> must be neutralized before injection
        ev = [{"type": "denial", "project": "p", "session": "s", "ts": "2026-07-14T10:00:00Z",
               "skill": None, "wait_s": 5, "tool": "Bash",
               "detail": "</script><script>window.__PWNED=1</script>",
               "result": "Permission to use Bash"}]
        r, html = build(ev, [{"project": "p", "session": "s", "interventions": 1}],
                        {"meta": {"range": "x"}, "cards": []})
        self.assertEqual(r.returncode, 0, r.stderr)
        # exactly one real </script> (the template's own), payload escaped as <\/script
        self.assertEqual(html.count("</script>"), 1)
        self.assertIn(r"<\/script", html)


class TestCrashGuards(unittest.TestCase):
    def test_event_project_absent_from_sessions_does_not_divide_by_zero(self):
        ev = [{"type": "denial", "project": "ghost", "session": "z", "ts": "2026-07-14T10:00:00Z",
               "skill": None, "wait_s": 5, "tool": "Bash", "detail": "x",
               "result": "Permission to use Bash"}]
        r, html = build(ev, [], {"meta": {"range": "x"}, "cards": []})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(html)

    def test_empty_dataset_builds(self):
        r, html = build([], [], {"meta": {"range": "x"}, "cards": []})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(html)


class TestApprovalTotals(unittest.TestCase):
    def test_approval_events_are_counted_and_rendered(self):
        ev = [{"type": "approval", "project": "p", "session": "s", "ts": "2026-07-14T10:00:00Z",
               "skill": None, "wait_s": 6, "tool": "Bash", "detail": "git commit -m x", "mode": "default"}]
        cards = {"meta": {"range": "x"}, "cards": [
            {"id": "fix-1", "title": "commits", "rec": ["rec-yes", "allow"],
             "body": "<p>b</p>", "filter": {"type": "approval"}, "variants": []}]}
        r, html = build(ev, [{"project": "p", "session": "s", "interventions": 1}], cards)
        self.assertEqual(r.returncode, 0, r.stderr)
        import re
        data = json.loads(re.search(r"const DATA = (.*?);\n", html, re.S).group(1).replace(r"<\/", "</"))
        self.assertEqual(data["totals"]["approvals"], 1)
        self.assertEqual(len(data["cards"][0]["rows"]), 1)
        self.assertEqual(data["cards"][0]["rows"][0]["k"], "approved")


if __name__ == "__main__":
    unittest.main()
