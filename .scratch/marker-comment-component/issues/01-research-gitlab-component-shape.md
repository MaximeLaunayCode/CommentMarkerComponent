Title: Research GitLab CI Component Shape
Type: research
Status: resolved

## Question

What GitLab CI Component structure, metadata, inputs, and publication conventions should this project follow for a reusable component whose v1 behavior is MR-only and patch-only?

## Expected answer

Summarize the relevant GitLab component docs and produce the recommended component file layout, input names, defaults, and a minimal consuming-project example.

## Answer

Research summary: [GitLab CI Component Shape](../research/01-gitlab-component-shape.md)

Decision: use a single GitLab CI Component named `marker-comment`, published from `templates/marker-comment/template.yml`, configured primarily through `spec:inputs`, and documented with top-level plus component-specific README content. Keep v1 MR-only and patch-only. Do not rely on helper scripts being available in consuming projects; either keep the job script inline for v1 or use a versioned image built by the component project release pipeline.

Recommended v1 inputs: `job-name`, `stage`, mandatory `marker-text`, `fail-when-patch-needed`, `file-globs`, `exclude-globs`, and `api-token-variable`. V1 uses the fixed patch path `marker-comment.patch`; configurability is deferred to [Support Configurable Patch Artifact Path](../backlog/configurable-patch-path.md). Exact file glob semantics remain owned by [Decide File Exclusions](05-decide-file-exclusions.md), and report-only behavior remains owned by [Decide Patch Artifact UX](06-decide-patch-artifact-ux.md).
