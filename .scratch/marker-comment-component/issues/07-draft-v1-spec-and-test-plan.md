Title: Draft V1 Spec and Test Plan
Type: task
Status: resolved
Blocked by: 01, 02, 03, 04, 05, 06

## Question

Using the resolved decisions, draft the v1 implementation spec and focused test plan for the GitLab CI Component.

## Expected answer

Produce a spec covering component inputs, job behavior, file discovery, marker rendering, the final patch-generation algorithm, patch artifact behavior, exclusions, idempotency, and tests. Include a focused test matrix and a minimal sample consuming-project configuration.

## Answer

Specification: [Marker Comment GitLab CI Component — V1 Specification](../spec.md)

The v1 implementation route is now explicit: publish one `marker-comment` component backed by a release-aligned processor image; discover MR-Added Files from the local MR diff; apply the fixed allowlist, glob narrowing, and exclusions; render syntax-aware canonical blocks without partially rewriting an invalid file; generate `marker-comment.patch` from a verified-clean checkout; and use stable `0`/`1`/`2` outcomes with an always-declared, non-empty-only artifact.

The specification fixes the public inputs, safe placement and overwrite rules, deterministic logs, partial-patch behavior, focused test matrix, release gate, minimal consumer configuration, and v1 boundaries. No unresolved fog or additional planning ticket surfaced.
