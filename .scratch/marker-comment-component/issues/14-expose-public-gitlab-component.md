# 14 — Expose the Processor as the Public GitLab CI Component

**What to build:** Let a consuming project include one `marker-comment` component and receive exactly one configurable merge-request job backed by an immutable processor image. The public inputs, job isolation, patch artifact, and exit behavior match the v1 consumer contract.

**Blocked by:** 09 — Harden MR-Added File Discovery and Workspace Validation; 13 — Reconcile Existing Marker Comment Blocks.

**Status:** ready-for-agent

- [ ] The component declares the required marker text and all specified defaults and input types, including custom job name, stage, enforcement mode, globs, and sentinels.
- [ ] The included configuration adds exactly one public job named from the input, runs only for merge request pipelines, uses full Git history, and defines no forbidden global configuration.
- [ ] The job invokes the image's internal processor command and passes public inputs without exposing the processor CLI as part of the consumer contract.
- [ ] The immutable image reference is tied to the same component release rather than the consuming project's registry image or repository helper files.
- [ ] The job always declares an artifact named for the short commit SHA, with the fixed patch path and one-week expiry; no patch file exists on no-change paths.
- [ ] A non-empty patch remains collectable after enforcement exit `1`, Report-Only exit `0`, and processing-error exit `2` with valid partial changes.
- [ ] GitLab CI lint and consuming-project fixtures verify default and custom names/stages, MR-versus-push selection, every artifact-bearing outcome, and the no-change outcome.
