# 08 — Generate a Marker Comment Patch for an Added Hash-Comment File

**What to build:** Deliver the smallest complete Marker Comment workflow for an ordinary hash-comment MR-Added File. With valid merge request inputs, the processor inserts the configured Marker Comment Block, produces an apply-ready patch, reports the outcome deterministically, and honors enforcement and Report-Only Mode. Applying the patch and running again produces no change.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] An added hash-comment file without a Marker Comment Block produces a standard, binary-capable Git patch containing the canonical configured block.
- [ ] The patch is written only when non-empty and applies cleanly to the unchanged source checkout.
- [ ] Enforcement exits `1` when a patch is needed; Report-Only Mode exits `0`; an already canonical file exits `0` without a patch.
- [ ] The summary always reports discovered, eligible, changed, excluded, and errored counts and includes the required patch-application guidance when a patch exists.
- [ ] Applying the generated patch and rerunning with identical inputs produces `No Marker Comment Block changes needed.` and no worktree change.
- [ ] Processor tests exercise the complete workflow in temporary Git repositories.
