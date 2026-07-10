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
- [Decide Marker Comment Syntax](issues/03-decide-marker-comment-syntax.md) -- process an adjustable default allowlist backed by deterministic comment-syntax mappings, report rather than fail on files outside it, and insert mapped marker blocks after shebang/XML declarations when needed.
- [Decide Idempotency and Existing Markers](issues/04-decide-idempotency-and-existing-markers.md) -- identify blocks by exact syntax-aware sentinels, always overwrite managed content in v1, reject malformed or duplicate markers, and do not migrate changed sentinel labels.
- [Decide File Exclusions](issues/05-decide-file-exclusions.md) -- use a published supported-syntax allowlist narrowed by `file-globs`, then apply built-in and consumer exclusions; report every excluded MR-added file with its reason and impose no size limit.
- [Decide Patch Artifact UX](issues/06-decide-patch-artifact-ux.md) -- use a fixed `marker-comment.patch` artifact retained for one week, deterministic summaries and apply instructions, distinct drift/error exit codes, and optional Report-Only Mode.
- [Draft V1 Spec and Test Plan](issues/07-draft-v1-spec-and-test-plan.md) -- consolidate the resolved decisions into the implementation-ready v1 component contract, patch algorithm, focused test matrix, release gate, and minimal consumer configuration.

## Not yet specified

- None.

## Out of scope

- [Support push pipelines without merge requests](backlog/push-mode.md) -- deferred beyond v1; v1 only targets merge request pipelines.
- [Support automatic commit and push strategy](backlog/commit-strategy.md) -- deferred beyond v1; v1 only produces a patch artifact.
- [Support Preserving Existing Marker Blocks](backlog/preserve-existing-marker-block.md) -- deferred beyond v1; v1 always restores the canonical body and position.
- [Support Configurable Patch Artifact Path](backlog/configurable-patch-path.md) -- deferred beyond v1; v1 always writes `marker-comment.patch` at the job workspace root.
