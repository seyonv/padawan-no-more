"""Tests for the inferred approved-prompt detection (the `approval` event).

Approvals aren't logged by Claude Code, so scan.py infers them: a mutating tool
that ran successfully, in a mode where a prompt was possible, with no allow-rule
covering it. These tests pin that behavior — especially the conservative edges,
since a false positive here would misreport the user's autonomy.
"""
import tempfile
import unittest
from helpers import run_scan, assistant, result, mode_line, of_type


def details(data):
    return [e["detail"] for e in of_type(data, "approval")]


class TestApprovalDetection(unittest.TestCase):
    def test_uncovered_mutating_tool_is_flagged(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "npm run build"}}]),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(details(data), ["npm run build"])

    def test_covered_command_is_not_flagged(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "git status"}}]),
                result("t1", "clean")]
        data = run_scan({"-proj-app": rows},
                        settings={"allow": ["Bash(git status)"], "deny": []})
        self.assertEqual(details(data), [])

    def test_wildcard_allow_covers_family(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "git commit -m x"}}]),
                result("t1", "done")]
        data = run_scan({"-proj-app": rows},
                        settings={"allow": ["Bash(git commit *)"], "deny": []})
        self.assertEqual(details(data), [])

    def test_bare_tool_allow_covers_all_uses(self):
        rows = [assistant([{"id": "t1", "name": "Edit", "input": {"file_path": "/proj/app/a.py"}}]),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Edit"], "deny": []})
        self.assertEqual(details(data), [])

    def test_permissive_setup_flags_nothing(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "anything goes"}}]),
                result("t1", "ok"),
                assistant([{"id": "t2", "name": "Write", "input": {"file_path": "/proj/app/z"}}]),
                result("t2", "ok")]
        data = run_scan({"-proj-app": rows},
                        settings={"allow": ["Bash(*)", "Write", "Edit"], "deny": []})
        self.assertEqual(details(data), [])

    def test_error_result_is_not_an_approval(self):
        rows = [assistant([{"id": "t1", "name": "Edit", "input": {"file_path": "/proj/app/x.py"}}]),
                result("t1", "boom", is_error=True)]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(details(data), [])

    def test_denied_result_is_a_denial_not_an_approval(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "curl x"}}]),
                result("t1", "Permission to use Bash with command curl x has been denied.")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(details(data), [])
        self.assertEqual(len(of_type(data, "denial")), 1)

    def test_read_only_tools_never_flagged(self):
        rows = [assistant([{"id": "t1", "name": "Read", "input": {"file_path": "/proj/app/x"}}]),
                result("t1", "contents"),
                assistant([{"id": "t2", "name": "Grep", "input": {"pattern": "x"}}]),
                result("t2", "match")]
        data = run_scan({"-proj-app": rows}, settings={"allow": [], "deny": []})
        self.assertEqual(details(data), [])


class TestApprovalModes(unittest.TestCase):
    def test_accept_edits_exempts_edits_but_not_bash(self):
        rows = [mode_line("acceptEdits"),
                assistant([{"id": "t1", "name": "Edit", "input": {"file_path": "/proj/app/y.py"}}]),
                result("t1", "ok"),
                assistant([{"id": "t2", "name": "Bash", "input": {"command": "docker build ."}}]),
                result("t2", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(details(data), ["docker build ."])

    def test_bypass_permissions_flags_nothing(self):
        rows = [mode_line("bypassPermissions"),
                assistant([{"id": "t1", "name": "Bash", "input": {"command": "rm something"}}]),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(details(data), [])

    def test_auto_mode_flags_nothing(self):
        rows = [mode_line("auto"),
                assistant([{"id": "t1", "name": "Write", "input": {"file_path": "/proj/app/q"}}]),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": [], "deny": []})
        self.assertEqual(details(data), [])


class TestApprovalDedupAndScope(unittest.TestCase):
    def test_repeated_command_family_counted_once_per_session(self):
        rows = [assistant([{"id": "t1", "name": "Edit", "input": {"file_path": "/proj/app/a.py"}}]),
                result("t1", "ok"),
                assistant([{"id": "t2", "name": "Edit", "input": {"file_path": "/proj/app/a.py"}}]),
                result("t2", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []})
        self.assertEqual(len(of_type(data, "approval")), 1)

    def test_project_local_allow_is_respected(self):
        cwd = tempfile.mkdtemp(prefix="pnm-proj-")
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "npm test"}}],
                          cwd=cwd),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows},
                        settings={"allow": ["Read"], "deny": []},
                        project_settings={cwd: {"allow": ["Bash(npm test)"]}})
        self.assertEqual(details(data), [])

    def test_no_approvals_flag_disables_detection(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "npm run build"}}]),
                result("t1", "ok")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Read"], "deny": []},
                        extra_args=["--no-approvals"])
        self.assertEqual(of_type(data, "approval"), [])


if __name__ == "__main__":
    unittest.main()
