# 10 — Apply Eligibility, Glob, and Exclusion Rules

**What to build:** Classify every MR-Added File deterministically as Eligible or Excluded using the published supported-syntax allowlist, optional allowlist narrowing, built-in exclusions, and consumer exclusions. Exclusions win and each excluded path is logged with one stable reason.

**Blocked by:** 08 — Generate a Marker Comment Patch for an Added Hash-Comment File.

**Status:** ready-for-agent

- [ ] The complete case-sensitive filename and extension mapping identifies the five supported comment-syntax families, including special build filenames and the exclusion of legacy fixed-form Fortran.
- [ ] `file-globs` narrows but never expands the supported-syntax allowlist, while `exclude-globs` adds exclusions that always win.
- [ ] Basename, rooted, `*`, `?`, `**`, and character-class patterns follow the documented Git-wildmatch-style behavior against repository-relative paths.
- [ ] Negation, directory-only, malformed, or otherwise unsupported patterns are rejected before file changes, identify the offending pattern, and exit `2`.
- [ ] Hidden paths, lockfiles, vendored segments, NUL-containing files, symlinks, submodules, and non-regular entries are excluded using the specified precedence; regular files are not excluded by size or generated-file inference.
- [ ] Every Excluded MR-Added File remains unchanged and is listed once, in bytewise path order, with the first applicable deterministic reason.
- [ ] When no Eligible MR-Added Files remain, the processor prints the specified success message, exits `0`, and creates no patch.
