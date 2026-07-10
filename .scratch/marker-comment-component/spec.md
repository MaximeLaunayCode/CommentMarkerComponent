# Marker Comment GitLab CI Component — V1 Specification

## Goal

Publish a reusable GitLab CI Component named `marker-comment` that inspects MR-Added Files, renders a configured Marker Comment Block into each Eligible MR-Added File, and emits an apply-ready patch when the checkout is not canonical.

V1 runs only in merge request pipelines. It never commits or pushes. When enforcement is enabled, a needed patch fails the job with stable instructions for applying, committing, and pushing the patch.

## Public component

- Component path: `templates/marker-comment/template.yml`.
- Public jobs: exactly one, named from the `job-name` input.
- Runtime: an immutable, versioned component image containing the marker processor and Git. The template must reference the image published for the same component release, not a helper file in the consuming repository and not the consuming project's `$CI_REGISTRY_IMAGE`.
- The image exposes one internal processor command. Its CLI is an implementation detail; `spec:inputs` is the public interface.
- The component defines no global `stages`, `default`, `before_script`, `after_script`, or top-level variables.
- The job has `rules` limiting it to `CI_PIPELINE_SOURCE == "merge_request_event"` and sets job-level `GIT_DEPTH: "0"`.

The component README must document the inputs, supported syntaxes, exclusions, exit codes, patch workflow, fork/history limitation, and the requirement for a consuming project to create merge request pipelines directly.

## Inputs

| Input | Type | Default | Contract |
| --- | --- | --- | --- |
| `marker-text` | string | none; required | Managed Marker Body text. It must contain at least one non-whitespace character. |
| `job-name` | string | `marker-comment` | Name of the job added to the consumer pipeline. |
| `stage` | string | `test` | Existing consumer stage in which the job runs. |
| `fail-when-patch-needed` | boolean | `true` | `false` enables Report-Only Mode. |
| `file-globs` | array | `[]` | Optional patterns that narrow the published supported-syntax allowlist. |
| `exclude-globs` | array | `[]` | Optional patterns added to the built-in exclusions. |
| `begin-sentinel` | string | `MARKER-COMMENT: BEGIN` | Exact begin label used to identify the managed block. |
| `end-sentinel` | string | `MARKER-COMMENT: END` | Exact end label used to identify the managed block. |

The fixed output path `marker-comment.patch` is not configurable in v1. There is no API-token input because v1 uses local Git discovery only.

Sentinel labels must be distinct, non-empty single lines without leading or trailing whitespace or NUL bytes. Invalid input or glob syntax is a configuration error detected before any file is changed. Marker text is split on universal line endings into logical lines; a final line terminator does not create an extra blank logical line. Trailing whitespace is removed from every line, leading whitespace and blank lines within the text are preserved.

## Supported files and comment syntax

Matching is case-sensitive. An MR-Added File enters the default allowlist through one of these mappings:

| Syntax | Filename or extension mapping |
| --- | --- |
| Hash line (`#`) | `.sh`, `.bash`, `.zsh`, `.ksh`, `.fish`, `.py`, `.rb`, `.yml`, `.yaml`, `.toml`; `Dockerfile`, `Dockerfile.*`, `Makefile`, `GNUmakefile`, `*.mk` |
| Slash line (`//`) | `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.java`, `.c`, `.h`, `.cc`, `.cpp`, `.cxx`, `.hpp`, `.cs`, `.go`, `.kt`, `.kts`, `.swift`, `.rs` |
| Bang line (`!`) | `.f90`, `.f95`, `.f03`, `.f08`, `.f18` |
| HTML block (`<!-- -->`) | `.html`, `.htm`, `.xml`, `.md`, `.markdown`, `.vue`, `.svelte` |
| CSS block (`/* */`) | `.css`, `.scss`, `.sass`, `.less` |

Legacy fixed-form Fortran extensions `.f`, `.for`, and `.ftn` are not supported by default. A `file-globs` pattern cannot make an unsupported syntax eligible; it only narrows this table.

Line-comment blocks render every sentinel and body line separately. Blank body lines retain the comment prefix. For example:

```text
# MARKER-COMMENT: BEGIN
# configured text
#
# second paragraph
# MARKER-COMMENT: END
```

CSS-family blocks render as one block comment:

```text
/* MARKER-COMMENT: BEGIN
 * configured text
 * MARKER-COMMENT: END */
```

HTML-family blocks render as one HTML comment:

```text
<!-- MARKER-COMMENT: BEGIN
     configured text
     MARKER-COMMENT: END -->
```

The processor must reject rendering that would create invalid comment syntax for a particular Eligible MR-Added File, such as `*/` in a CSS-family body or label, or `--` in an HTML-family body or label. That file is reported as a processing error and left unchanged; other files continue.

## Glob semantics and exclusions

`file-globs` and `exclude-globs` use documented Git-wildmatch-style patterns against repository-relative paths:

- `/` separates path segments, `*` and `?` do not cross `/`, `**` can cross segments, and character classes are supported.
- A pattern without `/` matches a basename at any depth; a leading `/` anchors at the repository root.
- Matching is case-sensitive. Negation and directory-only patterns are not supported.
- Every pattern is validated before processing. The error identifies the invalid pattern.

Eligibility is evaluated in this order:

1. The path must be an MR-Added File with a supported filename or extension mapping.
2. If `file-globs` is non-empty, the path must match at least one of them.
3. Built-in exclusions are applied.
4. `exclude-globs` are applied.

An exclusion always wins. Built-in exclusions are:

- any path containing a dot-prefixed segment, including a dotfile;
- exact lockfile basenames: `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `Cargo.lock`, `Gemfile.lock`, `poetry.lock`, `uv.lock`, `Pipfile.lock`, `composer.lock`, `go.sum`, `gradle.lockfile`, `packages.lock.json`, `Podfile.lock`, `mix.lock`, `pubspec.lock`, and `flake.lock`;
- any exact path segment `vendor`, `vendors`, `third_party`, `third-party`, `node_modules`, or `bower_components`;
- a file containing a NUL byte;
- a symlink, Git submodule entry, or anything other than a regular file.

There is no size exclusion and no generated-file inference in v1. Every Excluded MR-Added File is left unchanged and logged with one deterministic reason. If several reasons apply, report the first reason in the evaluation order above.

## MR-Added File discovery

The job requires an actual merge request pipeline and these predefined variables:

- `CI_MERGE_REQUEST_DIFF_BASE_SHA`
- `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`
- `CI_COMMIT_SHA`

It chooses the source head as:

```sh
head="${CI_MERGE_REQUEST_SOURCE_BRANCH_SHA:-$CI_COMMIT_SHA}"
```

The job fetches the target ref without tags, verifies the diff base locally with `git cat-file -e "${CI_MERGE_REQUEST_DIFF_BASE_SHA}^{commit}"`, then discovers paths with the equivalent of:

```sh
git diff --name-only --diff-filter=A -z "$CI_MERGE_REQUEST_DIFF_BASE_SHA" "$head" --
```

All path transport is NUL-delimited or uses argument arrays; paths are never split on whitespace or evaluated by a shell. Failure to fetch or find the base is a discovery error with guidance about full/fetchable target history. Fork merge requests whose pipeline cannot fetch parent target history are unsupported in v1 and fail this way.

The processor also verifies that the checkout represents the selected head and is clean before modification. A pre-existing file at the fixed output path is an error rather than something to overwrite.

## Marker placement and idempotency

The first safe content position is:

1. immediately after a leading shebang line;
2. otherwise, immediately after a leading XML declaration;
3. otherwise, byte zero.

The file's existing line-ending style is used for newly rendered lines; LF is used for an empty file. The block is adjacent to the preserved shebang or XML declaration and to following content: v1 adds no decorative blank separator. Apart from removing/replacing a managed block and inserting its canonical rendering, unrelated file bytes are preserved.

An existing Marker Comment Block is recognized only by exact, syntax-aware matches for the currently configured begin and end labels. Exactly one well-formed block is valid. Its Managed Marker Body is always replaced, and the whole block is moved to the first safe content position when necessary.

The following structures are errors and must not be guessed at or rewritten:

- a lone begin or end sentinel;
- an end sentinel before its begin sentinel;
- nested markers;
- more than one complete Marker Comment Block;
- a structurally invalid block comment.

A block using old sentinel labels is ordinary content. Changing labels causes insertion of a new managed block; v1 does not migrate the old one.

Running the processor twice with identical inputs and Git endpoints must produce no change on the second run.

## Processing and patch-generation algorithm

The implementation follows this order:

1. Validate all inputs, sentinel constraints, glob syntax, required CI variables, output-path safety, and clean checkout. On failure, change nothing and exit `2`.
2. Fetch and verify target history, select the source head, and discover the sorted set of MR-Added Files. On failure, change nothing and exit `2`.
3. For every MR-Added File, inspect the Git mode and path, determine syntax support, apply `file-globs`, then built-in and consumer exclusions. Record one reason for every Excluded MR-Added File.
4. Process Eligible MR-Added Files in bytewise repository-path order. Read each as bytes, choose its newline style and safe insertion point, validate syntax-specific renderability, and inspect current sentinels.
5. For a valid file, construct the entire candidate content in memory. Only replace the worktree file after all checks for that file pass. For a malformed or unrenderable file, leave it byte-for-byte unchanged, record the error, and continue.
6. Compare candidate bytes with the original. Replace only changed files, preserving executable mode. Record the changed path.
7. Generate a standard Git binary-capable patch from the clean checkout's worktree diff using stable `a/` and `b/` prefixes and no color or external diff. Because the checkout was verified clean, the diff contains only processor changes. Write it atomically to `$CI_PROJECT_DIR/marker-comment.patch` only when non-empty; remove no consumer file and leave no empty patch.
8. Print the deterministic summary and sections, then exit according to the precedence below.

The processor continues after per-file errors so a usable partial patch can be produced. Error status always outranks patch-needed status.

## Logs, artifact, and exit contract

The summary always contains counts for discovered, eligible, changed, excluded, and errored MR-Added Files. It is followed, when applicable, by sorted `Changed Files`, `Excluded MR-Added Files`, and `Errors` sections. Paths that are not safely printable are escaped consistently rather than emitted as control characters.

Special success messages are:

- `No Eligible MR-Added Files found.` when eligibility is empty;
- `No Marker Comment Block changes needed.` when eligible files are already canonical.

When a patch exists, the log names `marker-comment-$CI_COMMIT_SHORT_SHA`, states the one-week retention, and prints:

```sh
git apply --check marker-comment.patch
git apply marker-comment.patch
```

It then tells the developer to commit the applied changes and push them to the merge request source branch.

The template declares `artifacts:when: always`, name `marker-comment-$CI_COMMIT_SHORT_SHA`, path `marker-comment.patch`, and `expire_in: 1 week`. Since the processor creates the file only when it is non-empty, no patch artifact is uploaded on no-change paths. A non-empty patch is uploaded on enforcement failure, Report-Only Mode success, and exit `2` when valid files produced a partial patch.

Exit codes are stable:

- `0`: no patch is needed, or a patch is needed and `fail-when-patch-needed` is `false`;
- `1`: a patch is needed and `fail-when-patch-needed` is `true`;
- `2`: any configuration, discovery, malformed-marker, or processing error, whether or not a partial patch exists.

## Focused test plan

Processor tests run in temporary Git repositories and assert file bytes, modes, patch content, summaries, and exit status. Template tests compile the component through GitLab CI lint and exercise it in a consuming-project fixture. Golden files are appropriate for canonical rendering, logs, and patches; repeated runs must be included in idempotency cases.

| Area | Cases | Essential assertions |
| --- | --- | --- |
| Input validation | missing/blank `marker-text`; equal, multiline, or whitespace-padded sentinels; invalid glob; existing output path | exit `2`; named error; no modified files or patch |
| Discovery | normal detached MR; merged-results head override; missing base; target fetch failure; added/modified/deleted/renamed mix; spaces and shell metacharacters in paths | only diff-status `A`; correct head; NUL-safe paths; discovery failures exit `2` |
| Syntax mapping | one representative of each of five families; all special build filenames; case mismatch; legacy Fortran; unsupported extension | exact mapping; unsupported paths excluded, not errored |
| Exclusions | hidden segment; each vendored segment; representative lockfiles; NUL content; symlink; submodule; consumer glob; no size limit | exclusion wins; unchanged file; sorted path plus first reason |
| Glob behavior | basename, rooted, `*`, `?`, `**`, class, narrowing allowlist, exclusion overlap | documented Git-wildmatch behavior and precedence |
| Rendering | multiline text; trailing spaces; interior blank line; LF/CRLF; empty file; no terminal newline | exact canonical bytes and no unrelated normalization |
| Placement | ordinary file; shebang; XML declaration; shebang-like later line; XML declaration later in file | block at first safe content position only |
| Existing blocks | absent; canonical; stale body; valid block in wrong position; changed configured labels | insert/leave/overwrite/move behavior; old labels remain ordinary content |
| Malformed blocks | lone begin; lone end; reversed; nested; duplicate; invalid block syntax | affected file unchanged; all errors collected; exit `2` |
| Syntax safety | `*/` in CSS body/label; `--` in HTML body/label | affected file unchanged and reported; valid files still patched |
| Patch | one change; several syntaxes; executable file; no change; partial patch with another file errored | apply-check succeeds against clean head; fixed path; stable order; mode preserved; absent when empty |
| Exit/reporting | enforcement drift; Report-Only drift; no eligible files; all canonical; drift plus error | codes `1`, `0`, `0`, `0`, `2`; exact counts and deterministic sorted sections |
| Component integration | default and custom job names; custom stage; MR versus push pipeline; artifact on `0` report-only, `1`, and `2`; no-change path | component compiles; job selection correct; artifact name/path/expiry correct |
| End to end | consume a tagged component, add mixed eligible/excluded files, download and apply artifact, rerun | first run produces applicable patch; rerun is clean and exits `0` |

The release gate is: component lint passes; all processor and fixture tests pass; the sample consumer pipeline produces an apply-checkable patch; and the same fixture is clean after applying that patch.

## Minimal consuming-project configuration

```yaml
stages:
  - test

# This must live directly in the consuming project so GitLab creates MR pipelines.
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH'

include:
  - component: $CI_SERVER_FQDN/platform/ci-components/marker-comment@1.0.0
    inputs:
      stage: test
      marker-text: "Generated by internal platform policy"
```

Consumers may additionally set `file-globs`, `exclude-globs`, custom sentinel labels, a custom job name, or `fail-when-patch-needed: false`. Production consumers should pin a semantic release rather than a branch or `~latest`.

## Explicit v1 boundaries

- No push-pipeline mode.
- No automatic commit or push.
- No preservation policy for consumer-edited Managed Marker Bodies; canonical overwrite is mandatory.
- No configurable patch path.
- No API fallback for MR-Added File discovery.
- No generated-file inference, file-size cutoff, sentinel migration, or unsupported-syntax override.
