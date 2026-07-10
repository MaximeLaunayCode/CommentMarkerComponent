# 13 — Reconcile Existing Marker Comment Blocks

**What to build:** Make existing Marker Comment Blocks converge safely to the configured canonical form. A single valid block is updated and moved when needed, canonical content remains untouched, and ambiguous or malformed marker structures are reported without guessing or partially rewriting the affected file.

**Blocked by:** 11 — Render All Line-Comment Syntax Families; 12 — Render Safe HTML and CSS Block Comments.

**Status:** ready-for-agent

- [ ] Exact syntax-aware matches for the currently configured begin and end labels identify one well-formed Marker Comment Block in every supported syntax family.
- [ ] A valid block with a stale Managed Marker Body is replaced canonically, and a valid block in the wrong position is moved to the first safe content position without otherwise changing the file.
- [ ] A canonical block already at the safe position produces no file or patch change.
- [ ] Blocks using old sentinel labels remain ordinary content and a new block using the configured labels is inserted without migration.
- [ ] Lone, reversed, nested, duplicate, and structurally invalid markers leave the affected file byte-for-byte unchanged and produce a processing error.
- [ ] Processing continues after per-file errors, valid files contribute to a binary-capable partial patch, and error status `2` outranks enforcement or Report-Only Mode status.
- [ ] The final summary and Changed Files, Excluded MR-Added Files, and Errors sections are complete, deterministically ordered, and safely escape non-printable paths.
- [ ] Tests cover absent, canonical, stale, misplaced, relabeled, and every malformed block form across line and block syntax families, including repeated-run idempotency.
