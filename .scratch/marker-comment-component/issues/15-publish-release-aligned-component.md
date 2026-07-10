# 15 — Publish and Verify a Release-Aligned Component

**What to build:** Make the completed component consumable as a semantic release whose component and immutable processor image share a version. Give consumers complete operating guidance and prove the released workflow with an end-to-end project that applies the generated patch and becomes clean.

**Blocked by:** 14 — Expose the Processor as the Public GitLab CI Component.

**Status:** ready-for-agent

- [ ] The release workflow builds, tests, and publishes the processor image and component using the same semantic version, and production examples pin a semantic release.
- [ ] The component README documents every input, supported syntax mapping, glob semantics, built-in exclusions, exit code, artifact behavior, apply/commit/push workflow, and explicit v1 boundary.
- [ ] Consumer guidance explains that merge request pipelines must be created directly by the consuming project and documents the full/fetchable-history and fork limitation.
- [ ] Component lint, all processor and consuming-project fixture tests, and the sample consumer pipeline pass as release gates.
- [ ] A tagged component processes a fixture containing mixed Eligible and Excluded MR-Added Files and produces a patch that passes `git apply --check` against the clean source head.
- [ ] After applying that patch, the same fixture reruns cleanly, exits `0`, and creates no patch artifact.
- [ ] The released component never commits or pushes and requires no API token.
