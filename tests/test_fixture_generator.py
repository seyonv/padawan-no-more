import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "evals", "fixtures", "generate.py")


def _generate():
    out = tempfile.mkdtemp(prefix="pnm-fix-")
    subprocess.run([sys.executable, GEN, "--out", out], check=True,
                   capture_output=True, text=True)
    return out


def test_generates_all_scenarios_with_expected():
    out = _generate()
    names = sorted(os.listdir(out))
    assert len(names) == 12
    for n in names:
        assert os.path.isfile(os.path.join(out, n, "expected.json"))
        projects = os.path.join(out, n, "home", ".claude", "projects")
        assert os.path.isdir(projects) and os.listdir(projects)


def test_ceremony_scenario_ground_truth():
    out = _generate()
    exp = json.load(open(os.path.join(out, "ceremony-heavy", "expected.json")))
    assert exp["types"]["ask_question"] == 10 and exp["first_option"] == 9
