"""Regression tests for the scan.py parser fixes (the 2026-07-20 accuracy audit).

Each test pins a specific correction the audit surfaced against real transcripts,
so the wrong-but-plausible behavior can't creep back.
"""
import unittest
from helpers import run_scan, assistant, result, user_text, of_type, types


def ask_use(qid, question, options, ts="2026-07-19T10:00:00.000Z"):
    return assistant([{"id": qid, "name": "AskUserQuestion",
                       "input": {"questions": [{"question": question,
                                                "options": [{"label": o} for o in options]}]}}], ts=ts)


def ask_multi_use(qid, qs, ts="2026-07-19T10:00:00.000Z"):
    return assistant([{"id": qid, "name": "AskUserQuestion",
                       "input": {"questions": [{"question": q, "options": [{"label": o} for o in opts]}
                                               for q, opts in qs]}}], ts=ts)


def ask_result(qid, question, answer, ts="2026-07-19T10:05:00.000Z"):
    # matches the real Claude Code format: quoted answer, then ". You can now continue."
    text = f'Your questions have been answered: "{question}"="{answer}". You can now continue.'
    return result(qid, text, ts=ts)


class TestDenials(unittest.TestCase):
    def test_file_dump_containing_denied_string_is_not_a_denial(self):
        # a Read/Bash result that merely quotes the phrase must not count
        dump = "here is scan.py ... elif 'has been denied' in text ... more code"
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "cat scan.py"}}]),
                result("t1", dump)]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(of_type(data, "denial"), [])

    def test_real_denial_is_counted(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "rm x"}}]),
                result("t1", "Permission to use Bash with command rm x has been denied.")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(len(of_type(data, "denial")), 1)


class TestAnswerParsing(unittest.TestCase):
    def test_preview_suffix_answer_classifies_as_option_not_freetext(self):
        # preview-style options echo `Label" selected preview:…` after the label
        qid = "q1"
        rows = [ask_use(qid, "Which layout?", ["Sticky sidebar rail (Recommended)", "Topbar"]),
                result(qid, 'The user answered: "Which layout?"="Sticky sidebar rail (Recommended)" '
                            'selected preview:\n[ascii mockup]", "". You can now continue.')]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        asks = of_type(data, "ask_question")
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0]["kind"], "option")
        self.assertEqual(asks[0]["selected_rank"], 0)

    def test_recommended_first_option_is_rank_zero(self):
        rows = [ask_use("q1", "Language?", ["Python (Recommended)", "Go"]),
                ask_result("q1", "Language?", "Python (Recommended)")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(of_type(data, "ask_question")[0]["selected_rank"], 0)

    def test_genuine_freetext_stays_freetext(self):
        rows = [ask_use("q1", "Which DB?", ["Postgres", "SQLite"]),
                ask_result("q1", "Which DB?", "actually can we use my existing Mongo cluster")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(of_type(data, "ask_question")[0]["kind"], "freetext")


class TestWaitAttribution(unittest.TestCase):
    def test_multi_question_dialog_charges_wait_once(self):
        rows = [ask_multi_use("q1", [("First?", ["A", "B"]), ("Second?", ["C", "D"])],
                              ts="2026-07-19T10:00:00.000Z"),
                result("q1", 'Your questions have been answered: "First?"="A", "Second?"="C". '
                             'You can now continue.', ts="2026-07-19T10:10:00.000Z")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        asks = of_type(data, "ask_question")
        self.assertEqual(len(asks), 2)
        waited = [a for a in asks if a.get("wait_s")]
        self.assertEqual(len(waited), 1, "only the first question should carry the wait")


class TestInterruptions(unittest.TestCase):
    def test_for_tool_use_interruption_not_double_counted(self):
        # one Escape emits both a denial tool_result and a "for tool use" interruption
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "rm x"}}]),
                result("t1", "Permission to use Bash with command rm x has been denied."),
                user_text("[Request interrupted by user for tool use]")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(of_type(data, "interruption"), [])
        self.assertEqual(len(of_type(data, "denial")), 1)

    def test_standalone_interruption_is_counted(self):
        rows = [user_text("[Request interrupted by user]")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(len(of_type(data, "interruption")), 1)


class TestSkillAttribution(unittest.TestCase):
    def test_builtin_commands_not_captured_as_skills(self):
        rows = [user_text("<command-name>model</command-name>"),
                ask_use("q1", "Proceed?", ["Yes", "No"]),
                ask_result("q1", "Proceed?", "Yes")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertIsNone(of_type(data, "ask_question")[0]["skill"])

    def test_clear_resets_skill_attribution(self):
        rows = [user_text("<command-name>brainstorming</command-name>"),
                user_text("<command-name>clear</command-name>"),
                ask_use("q1", "Proceed?", ["Yes", "No"]),
                ask_result("q1", "Proceed?", "Yes")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertIsNone(of_type(data, "ask_question")[0]["skill"])


class TestSidechain(unittest.TestCase):
    def test_sidechain_events_are_skipped(self):
        rows = [assistant([{"id": "t1", "name": "Bash", "input": {"command": "rm x"}}],
                          extra={"isSidechain": True}),
                result("t1", "Permission to use Bash with command rm x has been denied.")]
        data = run_scan({"-proj-app": rows}, settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(data["events"], [])


class TestCrossFileDedup(unittest.TestCase):
    def test_same_event_in_two_session_files_counted_once(self):
        # a resumed session copies earlier history into a new file
        ask = ask_use("q1", "Proceed?", ["Yes", "No"])
        res = ask_result("q1", "Proceed?", "Yes")
        data = run_scan({"-proj-app": [ask, res], "-proj-app-resumed": [ask, res]},
                        settings={"allow": ["Bash(*)"], "deny": []})
        self.assertEqual(len(of_type(data, "ask_question")), 1)


if __name__ == "__main__":
    unittest.main()
