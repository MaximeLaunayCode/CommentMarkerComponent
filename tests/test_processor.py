from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from marker_comment.__main__ import CommentSyntax, comment_syntax_for


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

    def test_supported_filename_mapping_is_case_sensitive_and_complete(self) -> None:
        cases = {
            **{
                f"file{extension}": CommentSyntax.HASH_LINE
                for extension in [
                    ".sh",
                    ".bash",
                    ".zsh",
                    ".ksh",
                    ".fish",
                    ".py",
                    ".rb",
                    ".yml",
                    ".yaml",
                    ".toml",
                    ".mk",
                ]
            },
            "Dockerfile": CommentSyntax.HASH_LINE,
            "Dockerfile.release": CommentSyntax.HASH_LINE,
            "Makefile": CommentSyntax.HASH_LINE,
            "GNUmakefile": CommentSyntax.HASH_LINE,
            **{
                f"file{extension}": CommentSyntax.SLASH_LINE
                for extension in [
                    ".js",
                    ".jsx",
                    ".mjs",
                    ".cjs",
                    ".ts",
                    ".tsx",
                    ".java",
                    ".c",
                    ".h",
                    ".cc",
                    ".cpp",
                    ".cxx",
                    ".hpp",
                    ".cs",
                    ".go",
                    ".kt",
                    ".kts",
                    ".swift",
                    ".rs",
                ]
            },
            **{
                f"file{extension}": CommentSyntax.BANG_LINE
                for extension in [".f90", ".f95", ".f03", ".f08", ".f18"]
            },
            **{
                f"file{extension}": CommentSyntax.HTML_BLOCK
                for extension in [
                    ".html",
                    ".htm",
                    ".xml",
                    ".md",
                    ".markdown",
                    ".vue",
                    ".svelte",
                ]
            },
            **{
                f"file{extension}": CommentSyntax.CSS_BLOCK
                for extension in [".css", ".scss", ".sass", ".less"]
            },
            "legacy.f": None,
            "legacy.for": None,
            "legacy.ftn": None,
            "script.PY": None,
            "dockerfile": None,
            "unsupported.txt": None,
        }

        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(comment_syntax_for(Path(filename)), expected)

    def test_file_globs_cannot_expand_an_unsupported_syntax(self) -> None:
        self.add_file_at_head("notes.txt", "consumer notes\n")

        result = self.run_processor(
            "--marker-text", "Managed by platform", "--file-glob", "*.txt"
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "Summary: discovered=1 eligible=0 changed=0 excluded=1 errored=0",
            result.stdout,
        )
        self.assertIn("- notes.txt: unsupported comment syntax", result.stdout)
        self.assertEqual(
            (self.repository / "notes.txt").read_text(encoding="utf-8"),
            "consumer notes\n",
        )

    def test_all_supported_syntax_families_enter_workflow_eligibility(self) -> None:
        paths = ["hash.py", "slash.ts", "bang.f90", "page.html", "style.css"]
        for path in paths:
            self.add_file_at_head(path, f"original {path}\n")

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "Summary: discovered=5 eligible=5 changed=1 excluded=0 errored=0",
            result.stdout,
        )
        self.assertNotIn("Excluded MR-Added Files", result.stdout)
        self.assertTrue(
            (self.repository / "hash.py")
            .read_bytes()
            .startswith(b"# MARKER-COMMENT: BEGIN\n")
        )
        for path in paths[1:]:
            self.assertEqual(
                (self.repository / path).read_text(encoding="utf-8"),
                f"original {path}\n",
            )

    def test_invalid_globs_are_rejected_before_processing_and_name_the_pattern(
        self,
    ) -> None:
        self.add_file_at_head("scripts/check.py", "print('checked')\n")
        content_before = (self.repository / "scripts/check.py").read_bytes()
        status_before = self.git("status", "--short").stdout
        cases = [
            ("--file-glob", "!scripts/**"),
            ("--file-glob", "scripts/"),
            ("--exclude-glob", "scripts/[abc"),
            ("--exclude-glob", "scripts/[]"),
            ("--exclude-glob", r"scripts/\[literal.py"),
            ("--exclude-glob", ""),
        ]

        for option, pattern in cases:
            with self.subTest(pattern=pattern):
                result = self.run_processor(
                    "--marker-text", "Managed by platform", option, pattern
                )

                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(repr(pattern), result.stdout)
                self.assertEqual(
                    (self.repository / "scripts/check.py").read_bytes(), content_before
                )
                self.assertEqual(self.git("status", "--short").stdout, status_before)
                self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_file_globs_narrow_and_exclude_globs_win_with_wildmatch_semantics(
        self,
    ) -> None:
        paths = [
            "root.py",
            "nested/root.py",
            "src/app.py",
            "src/app1.py",
            "src/appA.py",
            "src/nested/skip.py",
            "deep/app3.py",
            "deep/src/app2.py",
            "docs/readme.py",
            "other/skip.py",
        ]
        for path in paths:
            self.add_file_at_head(path, f"original {path}\n")

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            "--file-glob",
            "/root.py",
            "--file-glob",
            "src/*.py",
            "--file-glob",
            "deep/**/app?.py",
            "--file-glob",
            "docs/readme.[p]y",
            "--exclude-glob",
            "app[1A].py",
            "--exclude-glob",
            "/docs/readme.py",
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "Summary: discovered=10 eligible=4 changed=4 excluded=6 errored=0",
            result.stdout,
        )
        for path in ["root.py", "src/app.py", "deep/app3.py", "deep/src/app2.py"]:
            self.assertTrue(
                (self.repository / path)
                .read_bytes()
                .startswith(b"# MARKER-COMMENT: BEGIN\n"),
                path,
            )
        for path in [
            "src/app1.py",
            "src/appA.py",
            "src/nested/skip.py",
            "nested/root.py",
            "docs/readme.py",
            "other/skip.py",
        ]:
            self.assertEqual(
                (self.repository / path).read_text(encoding="utf-8"),
                f"original {path}\n",
            )
        self.assertIn("- docs/readme.py: excluded by glob '/docs/readme.py'", result.stdout)
        self.assertIn("- src/app1.py: excluded by glob 'app[1A].py'", result.stdout)
        self.assertIn("- src/nested/skip.py: does not match file-globs", result.stdout)

    def test_builtin_exclusions_use_stable_precedence_and_do_not_infer_size(
        self,
    ) -> None:
        self.add_file_at_head(".config/tool.py", "hidden\n")
        self.add_file_at_head("src/vendor/tool.py", "vendored\n")
        self.add_file_at_head("pnpm-lock.yaml", "lockfileVersion: 9\n")

        binary_path = self.repository / "binary.py"
        binary_path.write_bytes(b"before\0after\n")
        self.git("add", "binary.py")
        self.git("commit", "--quiet", "-m", "add binary-like Python file")

        symlink = self.repository / "linked.py"
        symlink.symlink_to("README.txt")
        self.git("add", "linked.py")
        self.git("commit", "--quiet", "-m", "add symlink")

        large_content = "x" * (256 * 1024)
        self.add_file_at_head("large.py", large_content)

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            "--exclude-glob",
            "/.config/**",
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "Summary: discovered=6 eligible=1 changed=1 excluded=5 errored=0",
            result.stdout,
        )
        self.assertIn("- .config/tool.py: hidden path", result.stdout)
        self.assertIn("- binary.py: contains NUL byte", result.stdout)
        self.assertIn("- linked.py: symlink", result.stdout)
        self.assertIn("- pnpm-lock.yaml: lockfile", result.stdout)
        self.assertIn("- src/vendor/tool.py: vendored path", result.stdout)
        self.assertEqual((self.repository / "binary.py").read_bytes(), b"before\0after\n")
        self.assertTrue((self.repository / "linked.py").is_symlink())
        self.assertTrue(
            (self.repository / "large.py")
            .read_bytes()
            .startswith(b"# MARKER-COMMENT: BEGIN\n")
        )
        self.assertTrue((self.repository / "marker-comment.patch").exists())

    def test_git_submodule_entry_is_excluded_without_reading_the_worktree(self) -> None:
        self.git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.base},module.py",
        )
        self.git("commit", "--quiet", "-m", "add gitlink")
        (self.repository / "module.py").mkdir()

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "Summary: discovered=1 eligible=0 changed=0 excluded=1 errored=0",
            result.stdout,
        )
        self.assertIn("- module.py: Git submodule", result.stdout)
        self.assertIn("No Eligible MR-Added Files found.", result.stdout)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

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
