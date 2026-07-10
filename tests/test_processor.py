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
        self.git("remote", "add", "origin", ".")

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
        self.git("--literal-pathspecs", "add", path)
        self.git("commit", "--quiet", "-m", f"add {path}")

    def run_processor(
        self, *arguments: str, environment_overrides: dict[str, str | None] | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "CI_PROJECT_DIR": str(self.repository),
                "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.base,
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
                "CI_COMMIT_SHA": self.git("rev-parse", "HEAD").stdout.strip(),
                "CI_COMMIT_SHORT_SHA": self.git(
                    "rev-parse", "--short", "HEAD"
                ).stdout.strip(),
            }
        )
        environment.pop("CI_MERGE_REQUEST_SOURCE_BRANCH_SHA", None)
        environment["PYTHONPATH"] = str(PROJECT_ROOT)
        for name, value in (environment_overrides or {}).items():
            if value is None:
                environment.pop(name, None)
            else:
                environment[name] = value
        return subprocess.run(
            [sys.executable, "-m", "marker_comment", *arguments],
            cwd=self.repository,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_missing_target_branch_is_rejected_without_changing_the_workspace(
        self,
    ) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        status_before = self.git("status", "--short").stdout
        content_before = (self.repository / "scripts/check.py").read_bytes()

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            environment_overrides={"CI_MERGE_REQUEST_TARGET_BRANCH_NAME": None},
        )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_required_inputs_are_named_and_rejected_before_processing(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        content_before = (self.repository / "scripts/check.py").read_bytes()
        status_before = self.git("status", "--short").stdout
        cases = [
            ("CI_PROJECT_DIR", {"CI_PROJECT_DIR": None}),
            (
                "CI_MERGE_REQUEST_DIFF_BASE_SHA",
                {"CI_MERGE_REQUEST_DIFF_BASE_SHA": None},
            ),
            ("CI_COMMIT_SHA", {"CI_COMMIT_SHA": None}),
            ("CI_COMMIT_SHA", {"CI_COMMIT_SHA": " \t"}),
        ]

        for expected_error, overrides in cases:
            with self.subTest(expected_error=expected_error):
                result = self.run_processor(
                    "--marker-text",
                    "Managed by platform",
                    environment_overrides=overrides,
                )
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(expected_error, result.stdout)
                self.assertEqual(
                    (self.repository / "scripts/check.py").read_bytes(), content_before
                )
                self.assertEqual(self.git("status", "--short").stdout, status_before)
                self.assertFalse((self.repository / "marker-comment.patch").exists())

        blank_marker = self.run_processor("--marker-text", " \t\n")
        self.assertEqual(blank_marker.returncode, 2, blank_marker.stdout)
        self.assertIn("marker text", blank_marker.stdout)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_pre_existing_patch_is_rejected_without_overwriting_it(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        patch = self.repository / "marker-comment.patch"
        patch.write_bytes(b"consumer data\n")
        content_before = (self.repository / "scripts/check.py").read_bytes()
        status_before = self.git("status", "--short").stdout

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("output path already exists", result.stdout)
        self.assertEqual(patch.read_bytes(), b"consumer data\n")
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertEqual(self.git("status", "--short").stdout, status_before)

    def test_broken_symlink_at_patch_path_is_rejected_as_existing_output(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        patch = self.repository / "marker-comment.patch"
        patch.symlink_to("missing-consumer-file")
        status_before = self.git("status", "--short").stdout

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("output path already exists", result.stdout)
        self.assertTrue(patch.is_symlink())
        self.assertEqual(os.readlink(patch), "missing-consumer-file")
        self.assertEqual(self.git("status", "--short").stdout, status_before)

    def test_dirty_worktree_is_rejected_without_processing(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        path = self.repository / "scripts/check.py"
        path.write_text("print('locally edited')\n", encoding="utf-8")
        status_before = self.git("status", "--short").stdout

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("worktree must be clean", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertEqual(path.read_text(encoding="utf-8"), "print('locally edited')\n")
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_checkout_must_match_the_selected_source_head(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        status_before = self.git("status", "--short").stdout
        content_before = (self.repository / "scripts/check.py").read_bytes()

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            environment_overrides={"CI_COMMIT_SHA": self.base},
        )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("does not match the checked-out HEAD", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_unfetchable_target_history_has_actionable_guidance(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        self.git("remote", "set-url", "origin", str(self.repository / "missing"))
        content_before = (self.repository / "scripts/check.py").read_bytes()
        status_before = self.git("status", "--short").stdout

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("full, fetchable history", result.stdout)
        self.assertIn("fork merge requests", result.stdout)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_unavailable_diff_base_has_actionable_guidance(self) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        status_before = self.git("status", "--short").stdout
        content_before = (self.repository / "scripts/check.py").read_bytes()

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            environment_overrides={"CI_MERGE_REQUEST_DIFF_BASE_SHA": "f" * 40},
        )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("diff base is unavailable locally", result.stdout)
        self.assertIn("full clone", result.stdout)
        self.assertEqual(self.git("status", "--short").stdout, status_before)
        self.assertEqual(
            (self.repository / "scripts/check.py").read_bytes(), content_before
        )
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_normal_detached_pipeline_uses_commit_sha_as_source_head(self) -> None:
        self.add_file_at_head("source.py", "source\n")
        source_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "--quiet", "--detach", source_sha)

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Summary: discovered=1 eligible=1 changed=1", result.stdout)
        self.assertTrue(
            (self.repository / "source.py")
            .read_text(encoding="utf-8")
            .startswith("# MARKER-COMMENT: BEGIN\n")
        )

    def test_discovery_processes_added_files_but_not_other_diff_statuses(self) -> None:
        (self.repository / "modified.py").write_text("original\n", encoding="utf-8")
        (self.repository / "deleted.py").write_text("deleted\n", encoding="utf-8")
        (self.repository / "renamed.py").write_text("renamed\n", encoding="utf-8")
        self.git("add", "modified.py", "deleted.py", "renamed.py")
        self.git("commit", "--quiet", "-m", "add base fixtures")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

        (self.repository / "modified.py").write_text("modified\n", encoding="utf-8")
        (self.repository / "deleted.py").unlink()
        self.git("mv", "renamed.py", "moved.py")
        (self.repository / "added.py").write_text("added\n", encoding="utf-8")
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "mixed statuses")

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Summary: discovered=1 eligible=1 changed=1", result.stdout)
        self.assertTrue(
            (self.repository / "added.py")
            .read_text(encoding="utf-8")
            .startswith("# MARKER-COMMENT: BEGIN\n")
        )
        self.assertEqual(
            (self.repository / "modified.py").read_text(encoding="utf-8"),
            "modified\n",
        )
        self.assertEqual(
            (self.repository / "moved.py").read_text(encoding="utf-8"),
            "renamed\n",
        )

    def test_merged_results_pipeline_prefers_source_branch_sha(self) -> None:
        self.add_file_at_head("source.py", "source\n")
        source_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.add_file_at_head("merge-result.py", "merged\n")
        merged_results_sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "--quiet", "--detach", source_sha)

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            environment_overrides={
                "CI_COMMIT_SHA": merged_results_sha,
                "CI_MERGE_REQUEST_SOURCE_BRANCH_SHA": source_sha,
            },
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Summary: discovered=1 eligible=1 changed=1", result.stdout)
        self.assertTrue(
            (self.repository / "source.py")
            .read_text(encoding="utf-8")
            .startswith("# MARKER-COMMENT: BEGIN\n")
        )
        self.assertFalse((self.repository / "merge-result.py").exists())

    def test_unusual_paths_are_processed_as_data_and_control_bytes_are_escaped(
        self,
    ) -> None:
        paths = ["space name.py", "semi;$(touch injected).py", "line\nbreak.py"]
        for path in paths:
            self.add_file_at_head(path, f"content for {path!r}\n")

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Summary: discovered=3 eligible=3 changed=3", result.stdout)
        self.assertIn("- line\\nbreak.py", result.stdout)
        self.assertLess(
            result.stdout.index("- line\\nbreak.py"),
            result.stdout.index("- semi;$(touch injected).py"),
        )
        self.assertLess(
            result.stdout.index("- semi;$(touch injected).py"),
            result.stdout.index("- space name.py"),
        )
        self.assertFalse((self.repository / "injected").exists())
        for path in paths:
            self.assertTrue(
                (self.repository / path)
                .read_text(encoding="utf-8")
                .startswith("# MARKER-COMMENT: BEGIN\n")
            )

    def test_git_pathspec_magic_in_a_filename_remains_literal(self) -> None:
        path = ":(literal)victim.py"
        self.add_file_at_head(path, "print('safe')\n")

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(
            (self.repository / path)
            .read_text(encoding="utf-8")
            .startswith("# MARKER-COMMENT: BEGIN\n")
        )
        patch = self.repository / "marker-comment.patch"
        self.assertTrue(patch.exists())
        self.assertIn(b"victim.py", patch.read_bytes())
        self.git("--literal-pathspecs", "restore", "--", path)
        self.git("apply", "--check", "marker-comment.patch")

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
        self.git("add", "bin/release.sh")
        self.git("commit", "--quiet", "-m", "apply marker comment patch")
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
