Title: Support Configurable Patch Artifact Path
Status: backlog

## Follow-up

Add an optional component input that lets consumers override where the generated patch file is written and collected as an artifact.

## Initial shape

V1 always uses `marker-comment.patch` at the root of the GitLab job workspace. A future override should validate that the configured path is non-empty, repository-relative, remains inside `$CI_PROJECT_DIR`, and does not overwrite an existing project file.
