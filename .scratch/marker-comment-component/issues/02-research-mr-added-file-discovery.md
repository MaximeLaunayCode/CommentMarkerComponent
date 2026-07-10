Title: Research MR-Added File Discovery
Type: research
Status: resolved

## Question

What is the most reliable way for a GitLab merge request pipeline job to identify MR-added files compared with the merge request target branch?

## Expected answer

Compare the viable approaches, including Git diff against the target branch and GitLab API-based MR changes, and recommend the v1 approach with its CI variables, checkout/fetch requirements, and known edge cases.

## Answer

Research summary: [MR-Added File Discovery](../research/02-mr-added-file-discovery.md)

Decision: v1 should discover MR-Added Files with local Git diff, not the GitLab MR diffs API. Use `CI_MERGE_REQUEST_DIFF_BASE_SHA` as the base and `${CI_MERGE_REQUEST_SOURCE_BRANCH_SHA:-$CI_COMMIT_SHA}` as the head, then run `git diff --name-only --diff-filter=A -z "$base" "$head" --`.

The component job should set job-level `GIT_DEPTH: "0"`, fetch the target branch ref, verify `CI_MERGE_REQUEST_DIFF_BASE_SHA` exists locally with `git cat-file`, and fail with a configuration message if the base SHA cannot be found. Keep API diff discovery as a future fallback only; `CI_JOB_TOKEN` does not cover the required MR diffs endpoint, and requiring a broader token would be unnecessary burden for v1.

Known edge cases: fork MR pipelines may not be able to fetch parent target history from the source project; merged-results pipelines should use `CI_MERGE_REQUEST_SOURCE_BRANCH_SHA` when present; the consuming project must define direct MR pipeline `workflow: rules` or job `rules` because rules supplied only by `include:component` do not create MR pipelines.
