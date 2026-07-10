from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


PATCH_NAME = "marker-comment.patch"
HASH_EXTENSIONS = {
    ".bash",
    ".fish",
    ".ksh",
    ".mk",
    ".py",
    ".rb",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
    ".zsh",
}
SLASH_EXTENSIONS = {
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".cs",
    ".cxx",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
}
BANG_EXTENSIONS = {".f03", ".f08", ".f18", ".f90", ".f95"}
HTML_EXTENSIONS = {".htm", ".html", ".markdown", ".md", ".svelte", ".vue", ".xml"}
CSS_EXTENSIONS = {".css", ".less", ".sass", ".scss"}
LOCKFILE_NAMES = {
    "Cargo.lock",
    "Gemfile.lock",
    "Pipfile.lock",
    "Podfile.lock",
    "bun.lock",
    "bun.lockb",
    "composer.lock",
    "flake.lock",
    "go.sum",
    "gradle.lockfile",
    "mix.lock",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "packages.lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pubspec.lock",
    "uv.lock",
    "yarn.lock",
}
VENDORED_SEGMENTS = {
    "bower_components",
    "node_modules",
    "third-party",
    "third_party",
    "vendor",
    "vendors",
}


class CommentSyntax(Enum):
    HASH_LINE = "hash-line"
    SLASH_LINE = "slash-line"
    BANG_LINE = "bang-line"
    HTML_BLOCK = "html-block"
    CSS_BLOCK = "css-block"


class ExclusionReason(Enum):
    UNSUPPORTED_SYNTAX = "unsupported comment syntax"
    FILE_GLOB_MISMATCH = "does not match file-globs"
    HIDDEN_PATH = "hidden path"
    LOCKFILE = "lockfile"
    VENDORED_PATH = "vendored path"
    NUL_BYTE = "contains NUL byte"
    SYMLINK = "symlink"
    SUBMODULE = "Git submodule"
    NON_REGULAR = "non-regular Git entry"
    CONSUMER_GLOB = "excluded by glob"


@dataclass(frozen=True)
class GlobPattern:
    source: str
    matcher: re.Pattern[str]
    basename_only: bool

    def matches(self, path: Path) -> bool:
        candidate = path.name if self.basename_only else path.as_posix()
        return self.matcher.fullmatch(candidate) is not None


@dataclass(frozen=True)
class EligibleFile:
    path: Path
    syntax: CommentSyntax


@dataclass(frozen=True)
class ExcludedFile:
    path: Path
    reason: ExclusionReason
    pattern: str | None = None

    def description(self) -> str:
        if self.pattern is None:
            return self.reason.value
        return f"{self.reason.value} {self.pattern!r}"


class ProcessorError(Exception):
    """A configuration or discovery failure safe to report to the user."""


@dataclass(frozen=True)
class MergeRequestConfiguration:
    repository: Path
    diff_base_sha: str
    target_branch: str
    source_head_sha: str


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def comment_syntax_for(path: Path) -> CommentSyntax | None:
    name = path.name
    if (
        path.suffix in HASH_EXTENSIONS
        or name in {"Dockerfile", "Makefile", "GNUmakefile"}
        or name.startswith("Dockerfile.")
    ):
        return CommentSyntax.HASH_LINE
    if path.suffix in SLASH_EXTENSIONS:
        return CommentSyntax.SLASH_LINE
    if path.suffix in BANG_EXTENSIONS:
        return CommentSyntax.BANG_LINE
    if path.suffix in HTML_EXTENSIONS:
        return CommentSyntax.HTML_BLOCK
    if path.suffix in CSS_EXTENSIONS:
        return CommentSyntax.CSS_BLOCK
    return None


def render_block(marker_text: str, newline: bytes) -> bytes:
    lines = marker_text.splitlines()
    rendered = ["# MARKER-COMMENT: BEGIN"]
    rendered.extend(f"# {line.rstrip()}" if line.rstrip() else "#" for line in lines)
    rendered.append("# MARKER-COMMENT: END")
    return newline.join(line.encode() for line in rendered) + newline


def insertion_position(content: bytes) -> int:
    if not content.startswith(b"#!"):
        return 0
    line_end = content.find(b"\n")
    return len(content) if line_end == -1 else line_end + 1


def write_atomically(path: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(path)


def format_path(path: Path) -> str:
    """Render a repository path without emitting control characters."""
    rendered: list[str] = []
    escapes = {9: r"\t", 10: r"\n", 13: r"\r", 92: r"\\"}
    for byte in os.fsencode(path.as_posix()):
        if byte in escapes:
            rendered.append(escapes[byte])
        elif 32 <= byte <= 126:
            rendered.append(chr(byte))
        else:
            rendered.append(f"\\x{byte:02x}")
    return "".join(rendered)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Marker Comment Block changes")
    parser.add_argument("--marker-text", required=True)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--file-glob", action="append", default=[])
    parser.add_argument("--exclude-glob", action="append", default=[])
    return parser.parse_args()


def validate_glob(pattern: str) -> None:
    if not pattern:
        raise ProcessorError(f"invalid glob pattern {pattern!r}: pattern is empty")
    if pattern.startswith("!"):
        raise ProcessorError(
            f"invalid glob pattern {pattern!r}: negation is not supported"
        )
    if pattern.endswith("/"):
        raise ProcessorError(
            f"invalid glob pattern {pattern!r}: directory-only patterns are not supported"
        )
    if "\\" in pattern:
        raise ProcessorError(
            f"invalid glob pattern {pattern!r}: backslash escapes are not supported"
        )

def compile_glob(pattern: str) -> GlobPattern:
    validate_glob(pattern)
    rooted = pattern.startswith("/")
    normalized = pattern[1:] if rooted else pattern
    basename_only = not rooted and "/" not in normalized
    regex: list[str] = []
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character == "*":
            is_double_star = (
                index + 1 < len(normalized)
                and normalized[index + 1] == "*"
                and (index == 0 or normalized[index - 1] == "/")
                and (index + 2 == len(normalized) or normalized[index + 2] == "/")
            )
            if is_double_star:
                index += 2
                if index < len(normalized):
                    regex.append("(?:.*/)?")
                else:
                    regex.append(".*")
                    index -= 1
            else:
                regex.append("[^/]*")
        elif character == "?":
            regex.append("[^/]")
        elif character == "[":
            closing_index = normalized.find("]", index + 1)
            if closing_index == -1:
                raise ProcessorError(
                    f"invalid glob pattern {pattern!r}: unclosed character class"
                )
            content = normalized[index + 1 : closing_index]
            if not content or content == "!":
                raise ProcessorError(
                    f"invalid glob pattern {pattern!r}: empty character class"
                )
            negated = content.startswith("!")
            if negated:
                content = content[1:]
            escaped_content = content.replace("\\", "\\\\")
            if escaped_content.startswith("^"):
                escaped_content = "\\" + escaped_content
            regex.append(
                "(?!/)[" + ("^" if negated else "") + escaped_content + "]"
            )
            index = closing_index
        else:
            regex.append(re.escape(character))
        index += 1
    try:
        matcher = re.compile("".join(regex))
    except re.error as error:
        raise ProcessorError(f"invalid glob pattern {pattern!r}: {error}") from error
    return GlobPattern(pattern, matcher, basename_only)


def tracked_mode(repository: Path, path: Path) -> str:
    try:
        entry = git(
            repository,
            "--literal-pathspecs",
            "ls-files",
            "--stage",
            "-z",
            "--",
            path.as_posix(),
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ProcessorError(
            f"cannot inspect Git entry for {format_path(path)}: {detail}"
        ) from error
    if not entry:
        raise ProcessorError(f"MR-Added File is not tracked: {format_path(path)}")
    return entry.split(b" ", 1)[0].decode("ascii")


def built_in_exclusion(repository: Path, path: Path) -> ExclusionReason | None:
    segments = path.parts
    if any(segment.startswith(".") for segment in segments):
        return ExclusionReason.HIDDEN_PATH
    if path.name in LOCKFILE_NAMES:
        return ExclusionReason.LOCKFILE
    if any(segment in VENDORED_SEGMENTS for segment in segments):
        return ExclusionReason.VENDORED_PATH

    mode = tracked_mode(repository, path)
    if mode in {"100644", "100755"}:
        if b"\0" in (repository / path).read_bytes():
            return ExclusionReason.NUL_BYTE
        return None
    if mode == "120000":
        return ExclusionReason.SYMLINK
    if mode == "160000":
        return ExclusionReason.SUBMODULE
    return ExclusionReason.NON_REGULAR


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ProcessorError(f"required variable {name} is missing or blank")
    return value


def load_configuration(marker_text: str) -> MergeRequestConfiguration:
    if not marker_text.strip():
        raise ProcessorError("marker text must contain a non-whitespace character")

    repository = Path(required_environment("CI_PROJECT_DIR")).resolve()
    diff_base_sha = required_environment("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    target_branch = required_environment("CI_MERGE_REQUEST_TARGET_BRANCH_NAME")
    commit_sha = required_environment("CI_COMMIT_SHA")
    source_head_sha = (
        os.environ.get("CI_MERGE_REQUEST_SOURCE_BRANCH_SHA") or commit_sha
    )

    if not repository.is_dir():
        raise ProcessorError(f"CI_PROJECT_DIR is not a directory: {repository}")
    if os.path.lexists(repository / PATCH_NAME):
        raise ProcessorError(f"output path already exists: {PATCH_NAME}")

    try:
        selected_commit = git(
            repository, "rev-parse", "--verify", f"{source_head_sha}^{{commit}}"
        )
        checkout_commit = git(repository, "rev-parse", "--verify", "HEAD^{commit}")
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ProcessorError(f"selected source head is not a local commit: {detail}") from error

    if selected_commit.strip() != checkout_commit.strip():
        raise ProcessorError(
            "selected source head does not match the checked-out HEAD "
            f"({source_head_sha} != {checkout_commit.decode().strip()})"
        )

    try:
        workspace_status = git(
            repository, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ProcessorError(f"cannot inspect the Git worktree: {detail}") from error
    if workspace_status:
        raise ProcessorError("worktree must be clean before processing")

    return MergeRequestConfiguration(
        repository, diff_base_sha, target_branch, source_head_sha
    )


def discover_added_files(configuration: MergeRequestConfiguration) -> list[Path]:
    try:
        git(
            configuration.repository,
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/"
            f"{configuration.target_branch}:refs/remotes/origin/"
            f"{configuration.target_branch}",
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ProcessorError(
            "cannot fetch merge request target history; ensure the target branch has "
            "full, fetchable history (fork merge requests without access to parent "
            f"history are unsupported): {detail}"
        ) from error

    try:
        git(
            configuration.repository,
            "cat-file",
            "-e",
            f"{configuration.diff_base_sha}^{{commit}}",
        )
    except subprocess.CalledProcessError as error:
        raise ProcessorError(
            "merge request diff base is unavailable locally after fetching target "
            "history; use a full clone with fetchable target history "
            f"(fork limitations may apply): {configuration.diff_base_sha}"
        ) from error

    try:
        discovered_output = git(
            configuration.repository,
            "diff",
            "--name-only",
            "--diff-filter=A",
            "--find-renames",
            "-z",
            configuration.diff_base_sha,
            configuration.source_head_sha,
            "--",
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ProcessorError(f"cannot discover MR-Added Files: {detail}") from error

    return sorted(
        (Path(os.fsdecode(path)) for path in discovered_output.split(b"\0") if path),
        key=lambda path: os.fsencode(path.as_posix()),
    )


def main() -> int:
    arguments = parse_arguments()
    try:
        file_globs = [compile_glob(pattern) for pattern in arguments.file_glob]
        exclude_globs = [compile_glob(pattern) for pattern in arguments.exclude_glob]
        configuration = load_configuration(arguments.marker_text)
        discovered = discover_added_files(configuration)
    except ProcessorError as error:
        print(f"Error: {error}")
        return 2
    repository = configuration.repository
    eligible: list[EligibleFile] = []
    excluded: list[ExcludedFile] = []
    try:
        for path in discovered:
            syntax = comment_syntax_for(path)
            if syntax is None:
                excluded.append(
                    ExcludedFile(path, ExclusionReason.UNSUPPORTED_SYNTAX)
                )
            elif file_globs and not any(pattern.matches(path) for pattern in file_globs):
                excluded.append(
                    ExcludedFile(path, ExclusionReason.FILE_GLOB_MISMATCH)
                )
            else:
                reason = built_in_exclusion(repository, path)
                matching_exclusion = next(
                    (pattern for pattern in exclude_globs if pattern.matches(path)), None
                )
                if reason is not None:
                    excluded.append(ExcludedFile(path, reason))
                elif matching_exclusion is not None:
                    excluded.append(
                        ExcludedFile(
                            path,
                            ExclusionReason.CONSUMER_GLOB,
                            matching_exclusion.source,
                        )
                    )
                else:
                    eligible.append(EligibleFile(path, syntax))
    except ProcessorError as error:
        print(f"Error: {error}")
        return 2
    changed: list[Path] = []

    for eligible_file in eligible:
        if eligible_file.syntax is not CommentSyntax.HASH_LINE:
            continue
        relative_path = eligible_file.path
        path = repository / relative_path
        original = path.read_bytes()
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        block = render_block(arguments.marker_text, newline)
        position = insertion_position(original)
        candidate = (
            original
            if original[position:].startswith(block)
            else original[:position] + block + original[position:]
        )
        if candidate != original:
            path.write_bytes(candidate)
            changed.append(relative_path)

    patch_path = repository / PATCH_NAME
    if changed:
        patch = git(
            repository,
            "--literal-pathspecs",
            "diff",
            "--binary",
            "--no-color",
            "--no-ext-diff",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            "--",
            *(path.as_posix() for path in changed),
        )
        if patch:
            write_atomically(patch_path, patch)

    print(
        "Summary: "
        f"discovered={len(discovered)} eligible={len(eligible)} "
        f"changed={len(changed)} excluded={len(excluded)} errored=0"
    )
    if changed:
        print("Changed Files")
        for path in changed:
            print(f"- {format_path(path)}")
    if excluded:
        print("Excluded MR-Added Files")
        for excluded_file in excluded:
            print(
                f"- {format_path(excluded_file.path)}: {excluded_file.description()}"
            )
    if changed:
        artifact_sha = os.environ.get("CI_COMMIT_SHORT_SHA", "unknown")
        print(f"Patch artifact: marker-comment-{artifact_sha} (retained for one week)")
        print("git apply --check marker-comment.patch")
        print("git apply marker-comment.patch")
        print("Commit the applied changes and push them to the merge request source branch.")
        return 0 if arguments.report_only else 1

    if not eligible:
        print("No Eligible MR-Added Files found.")
    else:
        print("No Marker Comment Block changes needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
