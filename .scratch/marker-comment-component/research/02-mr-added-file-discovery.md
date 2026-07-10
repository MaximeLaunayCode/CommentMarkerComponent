# Research: MR-Added File Discovery

## Sources

- GitLab predefined CI/CD variables: https://docs.gitlab.com/ci/variables/predefined_variables/
- GitLab merge request pipelines: https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/
- GitLab merge requests API: https://docs.gitlab.com/api/merge_requests/
- GitLab CI/CD job token: https://docs.gitlab.com/ci/jobs/ci_job_token/

## Relevant GitLab Facts

Merge request pipeline jobs get MR-specific variables only when the pipeline is a merge request pipeline and the merge request is open. The variables relevant to MR-Added File discovery are:

- `CI_PIPELINE_SOURCE=merge_request_event`, used to limit the job to MR pipelines.
- `CI_MERGE_REQUEST_IID`, the project-level MR identifier.
- `CI_MERGE_REQUEST_DIFF_BASE_SHA`, the base SHA of the MR diff.
- `CI_MERGE_REQUEST_DIFF_ID`, the MR diff version.
- `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`, the target branch name.
- `CI_MERGE_REQUEST_SOURCE_BRANCH_SHA`, which is empty in normal detached MR pipelines and present only in merged-results pipelines.
- `CI_MERGE_REQUEST_TARGET_BRANCH_SHA`, which is also empty in normal detached MR pipelines and present only in merged-results pipelines.

`CI_COMMIT_BEFORE_SHA` is not useful here: GitLab documents it as all zeroes for merge request pipelines.

Merge request pipelines run on the source branch contents and ignore the target branch contents. The consuming project's own `.gitlab-ci.yml` must contain a direct `workflow: rules` or job `rules` entry for `CI_PIPELINE_SOURCE == "merge_request_event"`; rules supplied only through `include:component` do not satisfy GitLab's requirement to create MR pipelines.

For fork MRs, GitLab normally creates and runs the pipeline in the fork/source project using the fork's CI settings and variables. Parent-project members can manually run the fork MR pipeline in the parent project, but that has different trust and secret-exposure implications.

## Option 1: Local Git Diff

Use the MR diff base SHA and the source head checked out by the runner:

```sh
base="$CI_MERGE_REQUEST_DIFF_BASE_SHA"
head="${CI_MERGE_REQUEST_SOURCE_BRANCH_SHA:-$CI_COMMIT_SHA}"

git diff --name-only --diff-filter=A -z "$base" "$head" --
```

This produces NUL-delimited paths whose Git diff status is added between the MR diff base and source head. That matches the local definition of an MR-Added File: a file added by the merge request compared with the branch point from the target branch, not a file added in every individual commit.

Checkout/fetch requirements:

- Prefer setting the component job's `GIT_DEPTH` to `0` so the diff base commit is available reliably.
- Before diffing, fetch the target branch ref to make sure the repository has enough target-side history:

```sh
git fetch --no-tags origin \
  "+refs/heads/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}:refs/remotes/origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}"
git cat-file -e "${CI_MERGE_REQUEST_DIFF_BASE_SHA}^{commit}"
```

- If `git cat-file` fails, stop with a clear message explaining that the job needs full history or access to the target branch history.
- Use NUL-delimited output because MR-Added File paths can contain spaces or shell metacharacters.

Pros:

- Does not require an additional API token.
- Works from Git's file status, so large file contents and binary files do not need to be downloaded through the API.
- Avoids API diff size limits for file discovery because only names/status are needed.
- Lets the patch generator operate directly on the checked-out worktree.

Cons and edge cases:

- Requires the MR diff base commit to be available in the job clone. Shallow clones can break this unless the job fetches enough history or uses `GIT_DEPTH: "0"`.
- Fork MRs can be awkward when the source-project pipeline cannot fetch the parent target branch. For v1, treat this as unsupported unless the target history is available to the job.
- In merged-results pipelines, `CI_COMMIT_SHA` may point at the synthetic merge result. Use `CI_MERGE_REQUEST_SOURCE_BRANCH_SHA` when it is present; otherwise use `CI_COMMIT_SHA`.
- This gives file paths from Git. It does not expose GitLab UI metadata like `generated_file`; generated-file behavior should be handled by file exclusion rules if needed.

## Option 2: GitLab Merge Request Diffs API

The GitLab API endpoint:

```text
GET /projects/:id/merge_requests/:merge_request_iid/diffs
```

returns file-level diff entries with `new_file`, `new_path`, `old_path`, `renamed_file`, `deleted_file`, `generated_file`, `collapsed`, and `too_large`. Filtering entries with `new_file == true` gives GitLab's own MR-added file classification.

The older:

```text
GET /projects/:id/merge_requests/:merge_request_iid/changes
```

endpoint is deprecated and scheduled for removal in API v5, so v1 should not build on it.

Pros:

- Directly exposes GitLab's `new_file` flag.
- Can also expose `generated_file`, `collapsed`, and `too_large` metadata for reporting or exclusions.
- Avoids local target-branch fetch if the job has a suitable token.

Cons and edge cases:

- `CI_JOB_TOKEN` is not enough for this endpoint. GitLab documents CI job token access to the Merge requests API as limited to listing merge requests and getting a single merge request, not listing MR diffs.
- A personal access token, project access token, or future fine-grained job-token permission would add setup and security burden for consumers.
- The diffs endpoint is paginated and subject to merge request diff limits. The component would need pagination and clear handling for limited results.
- It couples v1 to API authentication and JSON parsing even though the job already has a Git worktree.

## Recommendation

V1 should use local Git diff as the primary and only required MR-Added File discovery method:

1. Run only in MR pipelines.
2. Require `CI_MERGE_REQUEST_DIFF_BASE_SHA`.
3. Choose `head="${CI_MERGE_REQUEST_SOURCE_BRANCH_SHA:-$CI_COMMIT_SHA}"`.
4. Ensure the base commit is available, preferably with job-level `GIT_DEPTH: "0"` plus a target branch fetch.
5. Discover MR-Added Files with `git diff --name-only --diff-filter=A -z "$base" "$head" --`.
6. Fail with a configuration message if the base SHA cannot be found.

Do not make the GitLab MR diffs API part of the v1 required path. Keep it as a possible future fallback or enhancement if consumers are willing to provide a token with access to `GET /projects/:id/merge_requests/:merge_request_iid/diffs`.

## Component Shape Implications

The component job should add job-level variables and checks similar to:

```yaml
"$[[ inputs.job-name ]]":
  variables:
    GIT_DEPTH: "0"
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - test -n "$CI_MERGE_REQUEST_DIFF_BASE_SHA" || { echo "This job requires a merge request pipeline."; exit 2; }
    - git fetch --no-tags origin "+refs/heads/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}:refs/remotes/origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}"
    - git cat-file -e "${CI_MERGE_REQUEST_DIFF_BASE_SHA}^{commit}" || { echo "Cannot find MR diff base SHA. Use full clone history or ensure target branch history is fetchable."; exit 2; }
    - head="${CI_MERGE_REQUEST_SOURCE_BRANCH_SHA:-$CI_COMMIT_SHA}"
    - git diff --name-only --diff-filter=A -z "$CI_MERGE_REQUEST_DIFF_BASE_SHA" "$head" -- > marker-comment.added-files
```

The consuming project must still define direct MR pipeline creation rules in its root `.gitlab-ci.yml`, for example:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH
```

That requirement belongs in the README and the sample consuming-project configuration.
