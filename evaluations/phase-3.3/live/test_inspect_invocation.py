"""Tests for inspect_invocation.py: a Skill call is counted as a LOAD only if the skill text reached the session, and
its timing is reported relative to the first file edit. Synthetic transcripts only."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

LIVE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "..", "..", "phase-3.2", "harness"))
import aqd_common as c  # noqa: E402
import inspect_invocation as ii  # noqa: E402

SKILL_TEXT = "\n".join(c.SKILL_SENTINELS)


def use(name, inp, ident):
    return {"type": "assistant", "message": {"model": "m", "content": [
        {"type": "tool_use", "id": ident, "name": name, "input": inp}]}}


def res(ident, text, is_error=False):
    block = {"type": "tool_result", "tool_use_id": ident, "content": text}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


SKILL = ("Skill", {"skill": "aqd-arm:code-discipline"})
EDIT = ("Edit", {"file_path": "a.py"})


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.store)
        self.schedule = {"runs": []}

    def add(self, run_id, group, events, invoked, loaded):
        cap = os.path.join(self.store, "captures", run_id)
        os.makedirs(os.path.join(cap, "driver"))
        with open(os.path.join(cap, "driver", "transcript.ndjson"), "w") as h:
            h.write(json.dumps({"type": "system", "subtype": "init"}) + "\n")
            for e in events:
                h.write(json.dumps(e) + "\n")
        with open(os.path.join(cap, "export-checks.json"), "w") as h:
            json.dump({"invoked": invoked, "skill_text_loaded": loaded}, h)
        self.schedule["runs"].append({"run_id": run_id, "group": group, "task": run_id, "order": len(self.schedule["runs"])})

    def test_loaded_before_the_first_edit(self):
        self.add("r-1", "treatment", [use(*SKILL, "s"), res("s", SKILL_TEXT), use(*EDIT, "e"), res("e", "ok")], True, True)
        (row,) = ii.inspect(self.store, self.schedule)
        self.assertEqual((row["called"], row["loaded"], row["call_error"], row["before_first_edit"]), (True, True, False, True))

    def test_failed_call_is_called_but_not_loaded(self):
        self.add("r-1", "treatment", [use(*SKILL, "s"), res("s", "<tool_use_error>no</tool_use_error>", True),
                                      use(*EDIT, "e"), res("e", "ok")], True, False)
        (row,) = ii.inspect(self.store, self.schedule)
        self.assertEqual((row["called"], row["loaded"], row["call_error"]), (True, False, True))

    def test_call_after_the_last_edit_is_flagged(self):
        self.add("r-1", "treatment", [use(*EDIT, "e"), res("e", "ok"), use(*SKILL, "s"), res("s", SKILL_TEXT)], True, True)
        (row,) = ii.inspect(self.store, self.schedule)
        self.assertEqual((row["loaded"], row["before_first_edit"]), (True, False))

    def test_no_edit_at_all_is_reported_as_none(self):
        self.add("r-1", "treatment", [use(*SKILL, "s"), res("s", SKILL_TEXT)], True, True)
        (row,) = ii.inspect(self.store, self.schedule)
        self.assertIsNone(row["before_first_edit"])

    def test_disagreement_with_the_harness_record_is_flagged(self):
        self.add("r-1", "treatment", [use(*SKILL, "s"), res("s", SKILL_TEXT)], False, False)
        (row,) = ii.inspect(self.store, self.schedule)
        self.assertTrue(row["disagrees_with_harness"])

    def test_controls_are_left_out_and_missing_captures_reported(self):
        self.add("r-c", "control", [use(*EDIT, "e")], False, False)
        self.schedule["runs"].append({"run_id": "r-x", "group": "treatment", "task": "T", "order": 9})
        rows = ii.inspect(self.store, self.schedule)
        self.assertEqual([(r["run_id"], r.get("missing")) for r in rows], [("r-x", True)])

    def test_cli_prints_counts_never_content(self):
        self.add("r-1", "treatment", [use(*SKILL, "s"), res("s", SKILL_TEXT), use(*EDIT, "e")], True, True)
        self.add("r-2", "treatment", [use(*SKILL, "s"), res("s", "err", True)], True, False)
        sched = os.path.join(self.store, "schedule.json")
        with open(sched, "w") as h:
            json.dump(self.schedule, h)
        out = io.StringIO()
        with redirect_stdout(out):
            code = ii.main(["--store", self.store, "--schedule", sched])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("called 2, loaded 1, loaded before the first edit 1, of 2 treatment runs", text)
        self.assertNotIn(c.SKILL_SENTINELS[0], text)


if __name__ == "__main__":
    unittest.main()
