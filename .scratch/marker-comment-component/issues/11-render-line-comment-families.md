# 11 — Render All Line-Comment Syntax Families

**What to build:** Extend canonical Marker Comment rendering to all supported line-comment files. Eligible hash, slash, and bang files preserve their existing bytes and file modes outside the managed block, including syntax-sensitive leading shebangs and the file's existing newline convention.

**Blocked by:** 10 — Apply Eligibility, Glob, and Exclusion Rules.

**Status:** ready-for-agent

- [ ] Every supported hash-line, slash-line, and bang-line filename or extension renders the exact syntax assigned by the public mapping.
- [ ] Marker text is split on universal line endings, trailing whitespace is removed per logical line, and leading whitespace and interior blank lines are preserved with a comment prefix.
- [ ] A terminal line ending in marker text does not create an additional blank Managed Marker Body line.
- [ ] A leading shebang remains first and the block is inserted immediately after it; shebang-like content elsewhere receives no special treatment.
- [ ] Existing LF or CRLF style is used for inserted lines, an empty file uses LF, and unrelated bytes including terminal-newline state are not normalized.
- [ ] Changed executable files retain their executable mode and unchanged files are not rewritten.
- [ ] Golden tests cover every line-comment family, special build filenames, multiline bodies, blank lines, newline variants, empty files, and files without terminal newlines.
