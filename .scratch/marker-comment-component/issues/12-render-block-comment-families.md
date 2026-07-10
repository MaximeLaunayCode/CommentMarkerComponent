# 12 — Render Safe HTML and CSS Block Comments

**What to build:** Extend canonical Marker Comment rendering to HTML-family and CSS-family files. Blocks use their published syntax, preserve XML declarations and surrounding bytes, and reject configured content that would make a comment invalid without preventing other valid files from producing changes.

**Blocked by:** 10 — Apply Eligibility, Glob, and Exclusion Rules.

**Status:** ready-for-agent

- [ ] Every supported HTML-family and CSS-family filename or extension renders the exact canonical block-comment form.
- [ ] A leading XML declaration remains first and the block is inserted immediately after it; declaration-like content elsewhere receives no special treatment.
- [ ] Marker text normalization, LF/CRLF preservation, empty-file behavior, and preservation of unrelated bytes match the line-comment contract.
- [ ] HTML-family rendering containing `--` in either sentinel or the Managed Marker Body is rejected for that file, which remains byte-for-byte unchanged.
- [ ] CSS-family rendering containing `*/` in either sentinel or the Managed Marker Body is rejected for that file, which remains byte-for-byte unchanged.
- [ ] A syntax-safety error is reported, processing continues for other Eligible MR-Added Files, and any valid changes remain available for the final partial patch.
- [ ] Golden tests cover canonical HTML and CSS rendering, XML placement, unsafe content, mixed valid/error inputs, and preserved surrounding bytes.
