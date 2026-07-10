Title: Decide Patch Artifact UX
Type: grilling
Status: resolved
Blocked by: 01, 02, 03, 04, 05

## Question

What should the v1 patch artifact and failed job output look like when marker comment block changes are needed?

## Expected answer

Define artifact names, retention expectations, job exit codes, console output, apply instructions, and the no-change success path.

## Answer

V1 always writes a non-empty generated patch to `marker-comment.patch` at the root of `$CI_PROJECT_DIR`. The path is fixed in v1: consumers do not configure it. A future override is tracked by [Support Configurable Patch Artifact Path](../backlog/configurable-patch-path.md).

GitLab uploads the patch in an artifact archive named `marker-comment-$CI_COMMIT_SHORT_SHA`, retained for one week. The artifact is present only when a non-empty patch was generated. It is uploaded for both enforcement and Report-Only Mode, and it remains available when the job encounters processing errors after producing a usable partial patch.

The job prints a deterministic summary with counts for discovered, eligible, changed, excluded, and errored MR-Added Files. It follows with sorted sections for changed files, Excluded MR-Added Files with inline reasons, and errors. When a patch exists, the output names the artifact and its expiry and gives these commands:

```sh
git apply --check marker-comment.patch
git apply marker-comment.patch
```

The output then tells the developer to commit the applied changes and push them to the merge request source branch. The component never commits or pushes in v1.

Exit codes are stable:

- `0`: no Marker Comment Block changes are needed, or changes are needed while Report-Only Mode is enabled.
- `1`: a valid patch is needed and enforcement is enabled.
- `2`: configuration, discovery, malformed-marker, or other processing errors occurred. If a usable partial patch also exists, upload it while still exiting `2`.

The `fail-when-patch-needed` input defaults to `true`. Setting it to `false` enables Report-Only Mode: patchable Marker Comment Block changes alone do not fail the job, but all processing errors retain exit code `2`.

Files without supported comment syntax are Excluded MR-Added Files and do not fail the job. If eligible files are already canonical, print `No Marker Comment Block changes needed.` If there are no eligible files, print `No Eligible MR-Added Files found.` Both paths exit `0` after printing the normal summary and exclusions, and neither creates a patch artifact.
