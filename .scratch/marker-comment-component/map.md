## Destination

Plan a reusable GitLab CI Component that other projects can include to add a configured marker comment block to each MR-added file. The first version is MR-only and patch-only: it generates a patch artifact and fails with clear apply instructions when marker changes are needed.

## Notes

- Domain terms live in `CONTEXT.md`; use `Marker Comment Block` and `MR-Added File` consistently.
- This is a planning map. Resolve tickets into decisions and a v1 implementation route, not production code.
- The first version explicitly excludes push-mode operation and automatic commit/push behavior. Track those as backlog follow-ups.
- Local tracker convention: tickets live in `.scratch/marker-comment-component/issues/`; backlog follow-ups live in `.scratch/marker-comment-component/backlog/`.

## Decisions so far

<!-- the index -- one line per closed ticket: enough to judge relevance, then zoom the link for the detail the ticket holds -->

- [Research GitLab CI Component Shape](issues/01-research-gitlab-component-shape.md) -- use one `marker-comment` component at `templates/marker-comment/template.yml`, configured with `spec:inputs`; keep v1 MR-only and patch-only, with inline logic or a versioned release image rather than consumer-visible helper files.
- [Research MR-Added File Discovery](issues/02-research-mr-added-file-discovery.md) -- discover MR-Added Files with local Git diff from `CI_MERGE_REQUEST_DIFF_BASE_SHA` to the source head, requiring full/fetchable history; leave GitLab MR diffs API as a future token-backed fallback.

## Not yet specified

- Final patch-generation algorithm shape, pending marker syntax, idempotency, file exclusion, and patch UX decisions.
- Final test matrix and sample consuming project configuration, pending the behavior decisions around file types, idempotency, and patch UX.
- Whether v1 should offer dry-run/report-only behavior in addition to patch generation.

## Out of scope

- [Support push pipelines without merge requests](backlog/push-mode.md) -- deferred beyond v1; v1 only targets merge request pipelines.
- [Support automatic commit and push strategy](backlog/commit-strategy.md) -- deferred beyond v1; v1 only produces a patch artifact.
