from __future__ import annotations

import argparse
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


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Marker Comment Block changes")
    parser.add_argument("--marker-text", required=True)
    parser.add_argument("--report-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    repository = Path(os.environ.get("CI_PROJECT_DIR", os.getcwd())).resolve()
    base = os.environ.get("CI_MERGE_REQUEST_DIFF_BASE_SHA")
    head = os.environ.get("CI_MERGE_REQUEST_SOURCE_BRANCH_SHA") or os.environ.get(
        "CI_COMMIT_SHA"
    )
    if not arguments.marker_text.strip() or not base or not head:
        print("Error: marker text and merge request Git endpoints are required.")
        return 2

    try:
        discovered_output = git(
            repository,
            "diff",
            "--name-only",
            "--diff-filter=A",
            "-z",
            base,
            head,
            "--",
        )
    except subprocess.CalledProcessError as error:
        print(error.stderr.decode(errors="replace").rstrip())
        return 2

    discovered = sorted(
        (Path(os.fsdecode(path)) for path in discovered_output.split(b"\0") if path),
        key=lambda path: os.fsencode(path.as_posix()),
    )
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
            print(f"- {path.as_posix()}")
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
