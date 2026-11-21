import tempfile
import unittest
from pathlib import Path
from scripts.validate_receipt import FIELDS, validate_text
from scripts.validate_skills import REQUIRED_SECTIONS, validate_skill

def valid_receipt():
    return "\n".join(f"{field}: example value" for field in FIELDS)

def valid_skill(root: Path, name="example-skill"):
    directory = root / name; directory.mkdir()
    sections = "\n".join(f"## {section}\nContent." for section in REQUIRED_SECTIONS)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A test skill description.\n---\n\n{sections}\n", encoding="utf-8")
    return directory

class ReceiptValidatorTests(unittest.TestCase):
    def test_accepts_complete_receipt(self): self.assertEqual(validate_text(valid_receipt()), [])
    def test_rejects_missing_field(self):
        content = "\n".join(f"{field}: value" for field in FIELDS if field != "Evidence")
        self.assertTrue(any("missing required field: Evidence" in e for e in validate_text(content)))
    def test_rejects_empty_field(self):
        self.assertTrue(any("empty field: Delivered" in e for e in validate_text(valid_receipt().replace("Delivered: example value", "Delivered:"))))
    def test_rejects_duplicate_field(self):
        self.assertTrue(any("duplicate field: Requested" in e for e in validate_text(valid_receipt() + "\nRequested: again")))
    def test_rejects_placeholders(self):
        self.assertTrue(any("placeholder" in e for e in validate_text(valid_receipt().replace("Evidence: example value", "Evidence: TBD"))))

class SkillValidatorTests(unittest.TestCase):
    def test_accepts_valid_skill(self):
        with tempfile.TemporaryDirectory() as tmp: self.assertEqual(validate_skill(valid_skill(Path(tmp)), "example-skill"), [])
    def test_rejects_wrong_name(self):
        with tempfile.TemporaryDirectory() as tmp: self.assertTrue(any("frontmatter name" in e for e in validate_skill(valid_skill(Path(tmp), "wrong-name"), "expected-name")))
    def test_rejects_missing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = valid_skill(Path(tmp)); path = directory / "SKILL.md"
            path.write_text(path.read_text().replace("## Workflow\nContent.\n", ""), encoding="utf-8")
            self.assertTrue(any("missing section '## Workflow'" in e for e in validate_skill(directory, "example-skill")))
    def test_rejects_missing_skill_file(self):
        with tempfile.TemporaryDirectory() as tmp: self.assertTrue(any("missing SKILL.md" in e for e in validate_skill(Path(tmp) / "absent", "absent")))

if __name__ == "__main__": unittest.main()
