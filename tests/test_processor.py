from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProcessorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Marker Comment Tests")
        self.git("config", "user.email", "marker-comment@example.test")
        (self.repository / "README.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "README.txt")
        self.git("commit", "--quiet", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def add_file_at_head(
        self, path: str, content: str, *, executable: bool = False
    ) -> None:
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        if executable:
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
        self.git("add", path)
        self.git("commit", "--quiet", "-m", f"add {path}")

    def run_processor(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CI_PROJECT_DIR": str(self.repository),
                "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.base,
                "CI_COMMIT_SHA": self.git("rev-parse", "HEAD").stdout.strip(),
                "CI_COMMIT_SHORT_SHA": self.git(
                    "rev-parse", "--short", "HEAD"
                ).stdout.strip(),
            }
        )
        environment["PYTHONPATH"] = str(PROJECT_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "marker_comment", *arguments],
            cwd=self.repository,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_enforcement_generates_an_apply_ready_patch_for_an_added_hash_comment_file(
        self,
    ) -> None:
        self.add_file_at_head(
            "scripts/check.py", "print('checked')\n", executable=True
        )

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_text(encoding="utf-8"),
            "# MARKER-COMMENT: BEGIN\n"
            "# Managed by platform\n"
            "# MARKER-COMMENT: END\n"
            "print('checked')\n",
        )
        patch = self.repository / "marker-comment.patch"
        self.assertTrue(patch.exists())
        patch_bytes = patch.read_bytes()
        self.assertTrue(patch_bytes)
        self.assertIn(b"diff --git a/scripts/check.py b/scripts/check.py", patch_bytes)
        self.assertTrue(
            (self.repository / "scripts/check.py").stat().st_mode & stat.S_IXUSR
        )
        self.git("restore", "scripts/check.py")
        self.git("apply", "--check", "marker-comment.patch")
        self.assertIn(
            "Summary: discovered=1 eligible=1 changed=1 excluded=0 errored=0",
            result.stdout,
        )
        self.assertIn("git apply --check marker-comment.patch", result.stdout)
        self.assertIn("git apply marker-comment.patch", result.stdout)

    def test_report_only_patch_can_be_applied_and_the_identical_rerun_is_clean(
        self,
    ) -> None:
        self.add_file_at_head("bin/release.sh", "#!/bin/sh\necho release\n")

        first_run = self.run_processor(
            "--marker-text", "Managed by platform", "--report-only"
        )

        self.assertEqual(first_run.returncode, 0, first_run.stdout)
        patch = self.repository / "marker-comment.patch"
        self.assertTrue(patch.exists())
        self.git("restore", "bin/release.sh")
        self.git("apply", "marker-comment.patch")
        patch.unlink()
        content_after_apply = (self.repository / "bin/release.sh").read_bytes()
        self.assertEqual(
            content_after_apply,
            b"#!/bin/sh\n"
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Managed by platform\n"
            b"# MARKER-COMMENT: END\n"
            b"echo release\n",
        )
        status_after_apply = self.git("status", "--short").stdout

        second_run = self.run_processor(
            "--marker-text", "Managed by platform", "--report-only"
        )

        self.assertEqual(second_run.returncode, 0, second_run.stdout)
        self.assertIn(
            "Summary: discovered=1 eligible=1 changed=0 excluded=0 errored=0",
            second_run.stdout,
        )
        self.assertIn("No Marker Comment Block changes needed.", second_run.stdout)
        self.assertFalse(patch.exists())
        self.assertEqual(
            (self.repository / "bin/release.sh").read_bytes(), content_after_apply
        )
        self.assertEqual(self.git("status", "--short").stdout, status_after_apply)


if __name__ == "__main__":
    unittest.main()
