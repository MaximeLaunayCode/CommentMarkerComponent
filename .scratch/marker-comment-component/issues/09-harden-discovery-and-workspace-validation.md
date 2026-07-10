# 09 — Harden MR-Added File Discovery and Workspace Validation

**What to build:** Make discovery and preflight checks safe for real merge request pipelines. The processor selects the correct source head, verifies fetchable target history and a canonical clean checkout, rejects unsafe output state before changing files, and handles repository paths without shell interpretation.

**Blocked by:** 08 — Generate a Marker Comment Patch for an Added Hash-Comment File.

**Status:** ready-for-agent

- [ ] All required merge request variables and processor inputs are validated before any file is changed, with configuration failures exiting `2` and naming the invalid condition.
- [ ] Normal detached pipelines use the commit SHA as the source head, while merged-results pipelines prefer the merge request source-branch SHA.
- [ ] Target history is fetched without tags, the diff base is verified as a local commit, and unavailable history produces actionable fork/full-history guidance without modifying files.
- [ ] Discovery selects only files added between the merge request diff base and selected source head; modified, deleted, and renamed paths are not treated as MR-Added Files.
- [ ] The selected head must match the checkout, the worktree must be clean, and a pre-existing patch output is rejected before processing.
- [ ] Paths containing spaces, control characters, or shell metacharacters remain data throughout discovery, sorting, processing, and reporting.
- [ ] Configuration and discovery tests assert exit status, unchanged worktree state, and absence of a patch on preflight failure.
