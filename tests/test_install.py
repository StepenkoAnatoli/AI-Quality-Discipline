import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.py"
SKILLS = ("code-discipline", "writing-specificity", "source-verification", "pr-hygiene")


def make_repo(root: Path, version: str = "v1") -> Path:
    repo = root / "repo"
    for name in SKILLS:
        folder = repo / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test skill\n---\n\n# {name}\n\n{version}\n",
            encoding="utf-8",
        )
    return repo


def run_cli(repo: Path, project: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-dir", str(repo), "--project-dir", str(project), *args],
        text=True, capture_output=True, check=False, env=env,
    )


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = make_repo(self.root)
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_does_not_write(self):
        result = run_cli(self.repo, self.project, "--target", "codex", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CREATE", result.stdout)
        self.assertFalse((self.project / ".agents").exists())
        self.assertFalse((self.project / ".ai-quality-discipline-manifest.json").exists())

    def test_install_and_repeat_are_idempotent(self):
        first = run_cli(self.repo, self.project, "--target", "codex")
        second = run_cli(self.repo, self.project, "--target", "codex")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.count("UNCHANGED"), 4)
        self.assertTrue((self.project / ".agents/skills/code-discipline/SKILL.md").is_file())

    def test_user_scope_uses_home_locations(self):
        home = self.root / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        cases = {"codex": ".agents/skills", "claude": ".claude/skills", "copilot": ".copilot/skills", "generic": ".agents/skills"}
        for target, relative in cases.items():
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-dir", str(self.repo), "--target", target, "--scope", "user", "--skills", "code-discipline"],
                text=True, capture_output=True, check=False, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((home / relative / "code-discipline/SKILL.md").is_file())
            import shutil
            shutil.rmtree(home / relative, ignore_errors=True)
            (home / ".ai-quality-discipline-manifest.json").unlink(missing_ok=True)

    def test_project_targets_use_documented_paths(self):
        cases = {"codex": ".agents/skills", "claude": ".claude/skills", "copilot": ".github/skills", "generic": ".agents/skills"}
        for target, relative in cases.items():
            project = self.root / ("project-" + target)
            project.mkdir()
            result = run_cli(self.repo, project, "--target", target, "--skills", "code-discipline")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((project / relative / "code-discipline/SKILL.md").is_file())

    def test_unmanaged_conflict_is_never_overwritten(self):
        dest = self.project / ".agents/skills/code-discipline/SKILL.md"
        dest.parent.mkdir(parents=True)
        dest.write_text("user file", encoding="utf-8")
        result = run_cli(self.repo, self.project, "--target", "codex", "--skills", "code-discipline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(dest.read_text(encoding="utf-8"), "user file")
        self.assertIn("CONFLICT", result.stdout)

    def test_managed_file_updates_only_if_unmodified(self):
        self.assertEqual(run_cli(self.repo, self.project, "--target", "codex").returncode, 0)
        make_repo(self.root, "v2")
        result = run_cli(self.repo, self.project, "--target", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        dest = self.project / ".agents/skills/code-discipline/SKILL.md"
        self.assertIn("v2", dest.read_text(encoding="utf-8"))

    def test_modified_managed_file_is_preserved(self):
        self.assertEqual(run_cli(self.repo, self.project, "--target", "codex").returncode, 0)
        dest = self.project / ".agents/skills/code-discipline/SKILL.md"
        dest.write_text(dest.read_text(encoding="utf-8") + "user edit\n", encoding="utf-8")
        make_repo(self.root, "v2")
        result = run_cli(self.repo, self.project, "--target", "codex")
        self.assertEqual(result.returncode, 2)
        self.assertIn("user edit", dest.read_text(encoding="utf-8"))

    def test_uninstall_removes_only_unchanged_managed_files(self):
        self.assertEqual(run_cli(self.repo, self.project, "--target", "codex").returncode, 0)
        edited = self.project / ".agents/skills/code-discipline/SKILL.md"
        edited.write_text(edited.read_text(encoding="utf-8") + "keep me\n", encoding="utf-8")
        result = run_cli(self.repo, self.project, "--target", "codex", "--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(edited.exists())
        self.assertFalse((self.project / ".agents/skills/writing-specificity/SKILL.md").exists())
        self.assertFalse((self.project / ".ai-quality-discipline-manifest.json").exists())

    def test_symlink_destination_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.project / ".agents").symlink_to(outside, target_is_directory=True)
        result = run_cli(self.repo, self.project, "--target", "codex", "--skills", "code-discipline")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((outside / "skills").exists())

    def test_tampered_manifest_cannot_target_arbitrary_project_files(self):
        manifest = self.project / ".ai-quality-discipline-manifest.json"
        manifest.write_text(json.dumps({"version": 1, "files": {
            "README.md": {"sha256": "0" * 64, "target": "codex", "skill": "code-discipline"}
        }}), encoding="utf-8")
        result = run_cli(self.repo, self.project, "--target", "codex", "--uninstall")
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside a known skill install path", result.stderr)

    def test_invalid_skill_metadata_is_rejected(self):
        path = self.repo / "skills/code-discipline/SKILL.md"
        path.write_text("---\nname: wrong-name\n---\n", encoding="utf-8")
        result = run_cli(self.repo, self.project, "--skills", "code-discipline")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.project / ".agents").exists())


if __name__ == "__main__":
    unittest.main()
