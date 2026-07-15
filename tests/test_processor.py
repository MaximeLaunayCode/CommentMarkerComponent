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

    def add_bytes_at_head(
        self, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
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
            "Summary: discovered=5 eligible=5 changed=5 excluded=0 errored=0",
            result.stdout,
        )
        self.assertNotIn("Excluded MR-Added Files", result.stdout)
        for path, prefix in {
            "hash.py": b"#",
            "slash.ts": b"//",
            "bang.f90": b"!",
        }.items():
            self.assertTrue(
                (self.repository / path).read_bytes().startswith(
                    prefix + b" MARKER-COMMENT: BEGIN\n"
                )
            )
        self.assertTrue(
            (self.repository / "page.html")
            .read_bytes()
            .startswith(b"<!-- MARKER-COMMENT: BEGIN\n")
        )
        self.assertTrue(
            (self.repository / "style.css")
            .read_bytes()
            .startswith(b"/* MARKER-COMMENT: BEGIN\n")
        )

    def test_line_comment_families_render_their_assigned_prefixes(self) -> None:
        cases = {
            "hash.py": "#",
            "slash.ts": "//",
            "bang.f90": "!",
        }
        for path in cases:
            self.add_file_at_head(path, f"original {path}\n")

        result = self.run_processor("--marker-text", "Managed by platform")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            "Summary: discovered=3 eligible=3 changed=3 excluded=0 errored=0",
            result.stdout,
        )
        for path, prefix in cases.items():
            with self.subTest(path=path):
                self.assertEqual(
                    (self.repository / path).read_text(encoding="utf-8"),
                    f"{prefix} MARKER-COMMENT: BEGIN\n"
                    f"{prefix} Managed by platform\n"
                    f"{prefix} MARKER-COMMENT: END\n"
                    f"original {path}\n",
                )

    def test_managed_marker_body_uses_universal_lines_without_a_terminal_blank(
        self,
    ) -> None:
        self.add_file_at_head("src/app.ts", "const answer = 42;\n")

        result = self.run_processor(
            "--marker-text", "  first  \r\n\r\n\tsecond\t \rthird\n"
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "src/app.ts").read_bytes(),
            b"// MARKER-COMMENT: BEGIN\n"
            b"//   first\n"
            b"//\n"
            b"// \tsecond\n"
            b"// third\n"
            b"// MARKER-COMMENT: END\n"
            b"const answer = 42;\n",
        )

    def test_line_comment_rendering_preserves_newlines_content_and_modes(self) -> None:
        fixtures = {
            "crlf.ts": b"const crlf = true;\r\n",
            "empty.f90": b"",
            "no-terminal.py": b"print('no terminal newline')",
            "later-shebang.py": b"print('first')\n#!/usr/bin/python\n",
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)
        self.add_bytes_at_head(
            "bin/tool.ts",
            b"#!/usr/bin/env node\r\nconsole.log('tool');\r\n",
            executable=True,
        )
        executable_mode = stat.S_IMODE((self.repository / "bin/tool.ts").stat().st_mode)

        result = self.run_processor("--marker-text", "Managed")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "crlf.ts").read_bytes(),
            b"// MARKER-COMMENT: BEGIN\r\n"
            b"// Managed\r\n"
            b"// MARKER-COMMENT: END\r\n"
            + fixtures["crlf.ts"],
        )
        self.assertEqual(
            (self.repository / "empty.f90").read_bytes(),
            b"! MARKER-COMMENT: BEGIN\n"
            b"! Managed\n"
            b"! MARKER-COMMENT: END\n",
        )
        self.assertEqual(
            (self.repository / "no-terminal.py").read_bytes(),
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Managed\n"
            b"# MARKER-COMMENT: END\n"
            + fixtures["no-terminal.py"],
        )
        self.assertEqual(
            (self.repository / "later-shebang.py").read_bytes(),
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Managed\n"
            b"# MARKER-COMMENT: END\n"
            + fixtures["later-shebang.py"],
        )
        self.assertEqual(
            (self.repository / "bin/tool.ts").read_bytes(),
            b"#!/usr/bin/env node\r\n"
            b"// MARKER-COMMENT: BEGIN\r\n"
            b"// Managed\r\n"
            b"// MARKER-COMMENT: END\r\n"
            b"console.log('tool');\r\n",
        )
        self.assertEqual(
            stat.S_IMODE((self.repository / "bin/tool.ts").stat().st_mode),
            executable_mode,
        )

    def test_unterminated_leading_shebang_remains_a_separate_first_line(self) -> None:
        self.add_bytes_at_head("bin/tool.sh", b"#!/bin/sh", executable=True)

        result = self.run_processor("--marker-text", "Managed")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "bin/tool.sh").read_bytes(),
            b"#!/bin/sh\n"
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Managed\n"
            b"# MARKER-COMMENT: END",
        )
        self.assertTrue((self.repository / "bin/tool.sh").stat().st_mode & stat.S_IXUSR)

        expected = (self.repository / "bin/tool.sh").read_bytes()
        (self.repository / "marker-comment.patch").unlink()
        self.git("add", "bin/tool.sh")
        self.git("commit", "--quiet", "-m", "apply marker block")

        second_result = self.run_processor("--marker-text", "Managed")

        self.assertEqual(second_result.returncode, 0, second_result.stdout)
        self.assertIn("eligible=1 changed=0", second_result.stdout)
        self.assertEqual((self.repository / "bin/tool.sh").read_bytes(), expected)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_every_supported_line_comment_mapping_has_canonical_golden_output(
        self,
    ) -> None:
        cases = [
            *[
                (f"hash/file{extension}", "#")
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
            ],
            ("build/Dockerfile", "#"),
            ("build/Dockerfile.release", "#"),
            ("build/Makefile", "#"),
            ("build/GNUmakefile", "#"),
            *[
                (f"slash/file{extension}", "//")
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
            ],
            *[
                (f"bang/file{extension}", "!")
                for extension in [".f90", ".f95", ".f03", ".f08", ".f18"]
            ],
        ]
        for path, _prefix in cases:
            destination = self.repository / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(f"original {path}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "add all line-comment mappings")

        result = self.run_processor("--marker-text", "Golden")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            f"Summary: discovered={len(cases)} eligible={len(cases)} "
            f"changed={len(cases)} excluded=0 errored=0",
            result.stdout,
        )
        for path, prefix in cases:
            with self.subTest(path=path):
                self.assertEqual(
                    (self.repository / path).read_text(encoding="utf-8"),
                    f"{prefix} MARKER-COMMENT: BEGIN\n"
                    f"{prefix} Golden\n"
                    f"{prefix} MARKER-COMMENT: END\n"
                    f"original {path}\n",
                )

    def test_canonical_line_comment_file_is_not_rewritten(self) -> None:
        content = (
            b"// MARKER-COMMENT: BEGIN\n"
            b"// Managed\n"
            b"// MARKER-COMMENT: END\n"
            b"const stable = true;\n"
        )
        self.add_bytes_at_head("stable.ts", content)
        path = self.repository / "stable.ts"
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        modified_at = path.stat().st_mtime_ns

        result = self.run_processor("--marker-text", "Managed")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("eligible=1 changed=0", result.stdout)
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(path.stat().st_mtime_ns, modified_at)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_stale_and_misplaced_line_comment_blocks_are_reconciled(self) -> None:
        fixtures = {
            "stale.py": (
                b"# MARKER-COMMENT: BEGIN\n"
                b"  # Consumer-edited text\n"
                b"# MARKER-COMMENT: END\n"
                b"print('kept')\n"
            ),
            "misplaced.ts": (
                b"const before = true;\r\n"
                b"// MARKER-COMMENT: BEGIN\r\n"
                b"// Old text\r\n"
                b"// MARKER-COMMENT: END\r\n"
                b"const after = true;\r\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "stale.py").read_bytes(),
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Canonical\n"
            b"# MARKER-COMMENT: END\n"
            b"print('kept')\n",
        )
        self.assertEqual(
            (self.repository / "misplaced.ts").read_bytes(),
            b"// MARKER-COMMENT: BEGIN\r\n"
            b"// Canonical\r\n"
            b"// MARKER-COMMENT: END\r\n"
            b"const before = true;\r\n"
            b"const after = true;\r\n",
        )
        self.assertIn("changed=2", result.stdout)

    def test_malformed_line_markers_leave_files_unchanged_and_keep_partial_patch(
        self,
    ) -> None:
        fixtures = {
            "a-lone-begin.py": b"# MARKER-COMMENT: BEGIN\nprint('kept')\n",
            "b-lone-end.ts": b"// MARKER-COMMENT: END\nconst kept = true;\n",
            "c-reversed.f90": (
                b"! MARKER-COMMENT: END\n"
                b"! MARKER-COMMENT: BEGIN\n"
                b"program kept\n"
            ),
            "d-nested.py": (
                b"# MARKER-COMMENT: BEGIN\n"
                b"# MARKER-COMMENT: BEGIN\n"
                b"# MARKER-COMMENT: END\n"
                b"# MARKER-COMMENT: END\n"
            ),
            "e-duplicate.ts": (
                b"// MARKER-COMMENT: BEGIN\n"
                b"// first\n"
                b"// MARKER-COMMENT: END\n"
                b"// MARKER-COMMENT: BEGIN\n"
                b"// second\n"
                b"// MARKER-COMMENT: END\n"
            ),
            "f-invalid.sh": (
                b"# MARKER-COMMENT: BEGIN\n"
                b"echo 'must stay outside managed comments'\n"
                b"# MARKER-COMMENT: END\n"
            ),
            "z-valid.py": b"print('valid')\n",
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor(
            "--marker-text", "Canonical", "--report-only"
        )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(
            "Summary: discovered=7 eligible=7 changed=1 excluded=0 errored=6",
            result.stdout,
        )
        for path in list(fixtures)[:-1]:
            with self.subTest(path=path):
                self.assertEqual((self.repository / path).read_bytes(), fixtures[path])
                self.assertIn(f"- {path}:", result.stdout)
        self.assertTrue(
            (self.repository / "z-valid.py")
            .read_bytes()
            .startswith(b"# MARKER-COMMENT: BEGIN\n# Canonical\n")
        )
        patch = self.repository / "marker-comment.patch"
        self.assertTrue(patch.exists())
        self.git("restore", "z-valid.py")
        self.git("apply", "--check", "marker-comment.patch")

    def test_canonical_blocks_before_required_preambles_are_moved(self) -> None:
        fixtures = {
            "tool.sh": (
                b"# MARKER-COMMENT: BEGIN\n"
                b"# Canonical\n"
                b"# MARKER-COMMENT: END\n"
                b"#!/bin/sh\n"
                b"echo kept\n"
            ),
            "document.xml": (
                b"<!-- MARKER-COMMENT: BEGIN\n"
                b"     Canonical\n"
                b"     MARKER-COMMENT: END -->\n"
                b'<?xml version="1.0"?>\n'
                b"<root>kept</root>\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "tool.sh").read_bytes(),
            b"#!/bin/sh\n"
            b"# MARKER-COMMENT: BEGIN\n"
            b"# Canonical\n"
            b"# MARKER-COMMENT: END\n"
            b"echo kept\n",
        )
        self.assertEqual(
            (self.repository / "document.xml").read_bytes(),
            b'<?xml version="1.0"?>\n'
            b"<!-- MARKER-COMMENT: BEGIN\n"
            b"     Canonical\n"
            b"     MARKER-COMMENT: END -->\n"
            b"<root>kept</root>\n",
        )

    def test_stale_and_misplaced_block_comments_are_reconciled(self) -> None:
        fixtures = {
            "stale.html": (
                b"<!-- MARKER-COMMENT: BEGIN\n"
                b"     Consumer-edited text\n"
                b"     MARKER-COMMENT: END -->\n"
                b"<main>kept</main>\n"
            ),
            "misplaced.css": (
                b"before { display: block; }\r\n"
                b"/* MARKER-COMMENT: BEGIN\r\n"
                b" * Old text\r\n"
                b" * MARKER-COMMENT: END */\r\n"
                b"after { display: block; }\r\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "stale.html").read_bytes(),
            b"<!-- MARKER-COMMENT: BEGIN\n"
            b"     Canonical\n"
            b"     MARKER-COMMENT: END -->\n"
            b"<main>kept</main>\n",
        )
        self.assertEqual(
            (self.repository / "misplaced.css").read_bytes(),
            b"/* MARKER-COMMENT: BEGIN\r\n"
            b" * Canonical\r\n"
            b" * MARKER-COMMENT: END */\r\n"
            b"before { display: block; }\r\n"
            b"after { display: block; }\r\n",
        )

    def test_malformed_block_markers_leave_every_affected_file_unchanged(
        self,
    ) -> None:
        fixtures = {
            "a-lone-begin.html": (
                b"<!-- MARKER-COMMENT: BEGIN\n<main>kept</main>\n"
            ),
            "b-lone-end.css": (
                b" * MARKER-COMMENT: END */\nbody { color: black; }\n"
            ),
            "c-reversed.html": (
                b"     MARKER-COMMENT: END -->\n"
                b"<!-- MARKER-COMMENT: BEGIN\n"
            ),
            "d-nested.css": (
                b"/* MARKER-COMMENT: BEGIN\n"
                b"/* MARKER-COMMENT: BEGIN\n"
                b" * MARKER-COMMENT: END */\n"
                b" * MARKER-COMMENT: END */\n"
            ),
            "e-duplicate.html": (
                b"<!-- MARKER-COMMENT: BEGIN\n"
                b"     first\n"
                b"     MARKER-COMMENT: END -->\n"
                b"<!-- MARKER-COMMENT: BEGIN\n"
                b"     second\n"
                b"     MARKER-COMMENT: END -->\n"
            ),
            "f-invalid.html": (
                b"<!-- MARKER-COMMENT: BEGIN\n"
                b"     closes -- too early -->\n"
                b"     MARKER-COMMENT: END -->\n"
            ),
            "g-invalid.css": (
                b"/* MARKER-COMMENT: BEGIN\n"
                b" * closes */ too early\n"
                b" * MARKER-COMMENT: END */\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(
            "Summary: discovered=7 eligible=7 changed=0 excluded=0 errored=7",
            result.stdout,
        )
        for path, content in fixtures.items():
            with self.subTest(path=path):
                self.assertEqual((self.repository / path).read_bytes(), content)
                self.assertIn(f"- {path}:", result.stdout)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_sentinels_in_separate_block_comments_are_structurally_invalid(
        self,
    ) -> None:
        fixtures = {
            "separate.html": (
                b"<!-- MARKER-COMMENT: BEGIN -->\n"
                b"<main>must not be claimed</main>\n"
                b"<!-- MARKER-COMMENT: END -->\n"
            ),
            "separate.css": (
                b"/* MARKER-COMMENT: BEGIN */\n"
                b"body { color: black; }\n"
                b"/* MARKER-COMMENT: END */\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("changed=0 excluded=0 errored=2", result.stdout)
        for path, content in fixtures.items():
            self.assertEqual((self.repository / path).read_bytes(), content)
            self.assertIn(f"- {path}: Marker Comment Block has invalid", result.stdout)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_old_sentinel_labels_are_ordinary_content(self) -> None:
        fixtures = {
            "legacy.py": (
                b"# OLD-MARKER: BEGIN\n"
                b"# Legacy body\n"
                b"# OLD-MARKER: END\n"
                b"print('kept')\n"
            ),
            "legacy.html": (
                b"<!-- OLD-MARKER: BEGIN\n"
                b"     Legacy body\n"
                b"     OLD-MARKER: END -->\n"
                b"<main>kept</main>\n"
            ),
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor(
            "--marker-text",
            "Canonical",
            "--begin-sentinel",
            "NEW-MARKER: BEGIN",
            "--end-sentinel",
            "NEW-MARKER: END",
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(
            (self.repository / "legacy.py").read_bytes(),
            b"# NEW-MARKER: BEGIN\n"
            b"# Canonical\n"
            b"# NEW-MARKER: END\n"
            + fixtures["legacy.py"],
        )
        self.assertEqual(
            (self.repository / "legacy.html").read_bytes(),
            b"<!-- NEW-MARKER: BEGIN\n"
            b"     Canonical\n"
            b"     NEW-MARKER: END -->\n"
            + fixtures["legacy.html"],
        )

    def test_managed_body_cannot_create_ambiguous_line_sentinels(self) -> None:
        fixtures = {
            "ambiguous.py": b"print('must stay')\n",
            "valid.html": b"<main>kept</main>\n",
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor(
            "--marker-text", "MARKER-COMMENT: BEGIN", "--report-only"
        )

        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("changed=1 excluded=0 errored=1", result.stdout)
        self.assertIn(
            "- ambiguous.py: Managed Marker Body conflicts with the configured sentinels",
            result.stdout,
        )
        self.assertEqual(
            (self.repository / "ambiguous.py").read_bytes(), fixtures["ambiguous.py"]
        )
        self.assertTrue(
            (self.repository / "valid.html")
            .read_bytes()
            .startswith(b"<!-- MARKER-COMMENT: BEGIN\n")
        )
        self.assertTrue((self.repository / "marker-comment.patch").exists())

    def test_reconciled_blocks_are_idempotent_on_the_next_run(self) -> None:
        self.add_bytes_at_head(
            "document.xml",
            b'<?xml version="1.0"?>\n'
            b"<root>before</root>\n"
            b"<!-- MARKER-COMMENT: BEGIN\n"
            b"     stale\n"
            b"     MARKER-COMMENT: END -->\n",
        )

        first = self.run_processor("--marker-text", "Canonical")
        self.assertEqual(first.returncode, 1, first.stdout)
        reconciled = (self.repository / "document.xml").read_bytes()
        (self.repository / "marker-comment.patch").unlink()
        self.git("add", "document.xml")
        self.git("commit", "--quiet", "-m", "apply reconciliation")

        second = self.run_processor("--marker-text", "Canonical")

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("eligible=1 changed=0", second.stdout)
        self.assertEqual((self.repository / "document.xml").read_bytes(), reconciled)
        self.assertFalse((self.repository / "marker-comment.patch").exists())

    def test_every_supported_block_comment_mapping_has_canonical_golden_output(
        self,
    ) -> None:
        cases = {
            **{
                f"html/file{extension}": (
                    "<!-- MARKER-COMMENT: BEGIN\n"
                    "     Golden\n"
                    "     MARKER-COMMENT: END -->\n"
                )
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
                f"css/file{extension}": (
                    "/* MARKER-COMMENT: BEGIN\n"
                    " * Golden\n"
                    " * MARKER-COMMENT: END */\n"
                )
                for extension in [".css", ".scss", ".sass", ".less"]
            },
        }
        for path in cases:
            destination = self.repository / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(f"original {path}\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "add all block-comment mappings")

        result = self.run_processor("--marker-text", "Golden")

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(
            f"Summary: discovered={len(cases)} eligible={len(cases)} "
            f"changed={len(cases)} excluded=0 errored=0",
            result.stdout,
        )
        for path, block in cases.items():
            with self.subTest(path=path):
                self.assertEqual(
                    (self.repository / path).read_text(encoding="utf-8"),
                    block + f"original {path}\n",
                )

    def test_block_rendering_preserves_xml_placement_newlines_and_surrounding_bytes(
        self,
    ) -> None:
        fixtures = {
            "document.xml": (
                b'<?xml version="1.0"\r\n encoding="UTF-8"?>\r\n'
                b"<root>kept</root>\r\n"
            ),
            "bom.xml": (
                b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\n'
                b"<root>kept</root>\n"
            ),
            "later.xml": b"<root/>\n<?xml declaration-like?>\n",
            "leading-like.xml": b"<?xml nonsense?>\n<root/>\n",
            "empty.css": b"",
            "no-terminal.html": b"<main>kept</main>",
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        result = self.run_processor(
            "--marker-text", "  first  \r\n\r\n\tsecond\t \rthird\n"
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        html_lf = (
            b"<!-- MARKER-COMMENT: BEGIN\n"
            b"       first\n"
            b"    \n"
            b"     \tsecond\n"
            b"     third\n"
            b"     MARKER-COMMENT: END -->\n"
        )
        html_crlf = html_lf.replace(b"\n", b"\r\n")
        self.assertEqual(
            (self.repository / "document.xml").read_bytes(),
            b'<?xml version="1.0"\r\n encoding="UTF-8"?>\r\n'
            + html_crlf
            + b"<root>kept</root>\r\n",
        )
        self.assertEqual(
            (self.repository / "bom.xml").read_bytes(),
            b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\n'
            + html_lf
            + b"<root>kept</root>\n",
        )
        self.assertEqual(
            (self.repository / "later.xml").read_bytes(),
            html_lf + fixtures["later.xml"],
        )
        self.assertEqual(
            (self.repository / "leading-like.xml").read_bytes(),
            html_lf + fixtures["leading-like.xml"],
        )
        self.assertEqual(
            (self.repository / "empty.css").read_bytes(),
            b"/* MARKER-COMMENT: BEGIN\n"
            b" *   first\n"
            b" *\n"
            b" * \tsecond\n"
            b" * third\n"
            b" * MARKER-COMMENT: END */\n",
        )
        self.assertEqual(
            (self.repository / "no-terminal.html").read_bytes(),
            html_lf + fixtures["no-terminal.html"],
        )

    def test_unsafe_sentinels_and_managed_marker_body_keep_a_partial_patch(
        self,
    ) -> None:
        fixtures = {
            "page.html": b"<main>kept</main>\n",
            "style.css": b"main { display: block; }\n",
            "valid.py": b"print('kept')\n",
        }
        for path, content in fixtures.items():
            self.add_bytes_at_head(path, content)

        cases = [
            (("--marker-text", "body--unsafe"), "page.html", "--"),
            (("--marker-text", "body*/unsafe"), "style.css", "*/"),
            (
                (
                    "--marker-text",
                    "Managed",
                    "--begin-sentinel",
                    "BEGIN--unsafe",
                ),
                "page.html",
                "--",
            ),
            (
                (
                    "--marker-text",
                    "Managed",
                    "--end-sentinel",
                    "END*/unsafe",
                ),
                "style.css",
                "*/",
            ),
        ]

        for arguments, unsafe_path, forbidden in cases:
            with self.subTest(arguments=arguments):
                result = self.run_processor(*arguments)

                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(
                    "Summary: discovered=3 eligible=3 changed=2 "
                    "excluded=0 errored=1",
                    result.stdout,
                )
                self.assertIn("Errors", result.stdout)
                self.assertIn(
                    f"- {unsafe_path}: comment syntax does not allow {forbidden!r}",
                    result.stdout,
                )
                self.assertEqual(
                    (self.repository / unsafe_path).read_bytes(),
                    fixtures[unsafe_path],
                )
                patch = self.repository / "marker-comment.patch"
                self.assertTrue(patch.exists())
                self.git("restore", *fixtures)
                self.git("apply", "--check", "marker-comment.patch")
                patch.unlink()

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

    def test_component_command_accepts_serialized_globs_and_boolean_enforcement(
        self,
    ) -> None:
        self.add_file_at_head("source.py", "source\n")
        self.add_file_at_head("ignored.js", "ignored\n")

        result = self.run_processor(
            "--marker-text",
            "Managed by platform",
            "--fail-when-patch-needed",
            "false",
            "--file-globs",
            '["*.py", "*.js"]',
            "--exclude-globs",
            '["ignored.*"]',
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "Summary: discovered=2 eligible=1 changed=1 excluded=1",
            result.stdout,
        )
        self.assertTrue(
            (self.repository / "source.py")
            .read_text(encoding="utf-8")
            .startswith("# MARKER-COMMENT: BEGIN\n")
        )
        self.assertEqual(
            (self.repository / "ignored.js").read_text(encoding="utf-8"),
            "ignored\n",
        )
        self.assertTrue((self.repository / "marker-comment.patch").exists())


if __name__ == "__main__":
    unittest.main()
