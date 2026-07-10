from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
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


def is_hash_comment_file(path: Path) -> bool:
    name = path.name
    return (
        path.suffix in HASH_EXTENSIONS
        or name in {"Dockerfile", "Makefile", "GNUmakefile"}
        or name.startswith("Dockerfile.")
    )


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
    return parser.parse_args()


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
        configuration = load_configuration(arguments.marker_text)
        discovered = discover_added_files(configuration)
    except ProcessorError as error:
        print(f"Error: {error}")
        return 2
    repository = configuration.repository
    eligible = [path for path in discovered if is_hash_comment_file(path)]
    excluded = [path for path in discovered if path not in eligible]
    changed: list[Path] = []

    for relative_path in eligible:
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
