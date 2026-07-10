Title: Support Push Pipelines Without Merge Requests
Status: backlog

## Follow-up

Add a future mode for projects that push directly to a branch such as `main` without using merge requests.

## Initial shape

The likely behavior is to detect files added in the pushed commit range, such as `CI_COMMIT_BEFORE_SHA..CI_COMMIT_SHA`, but the final design should be revisited after v1 MR mode is specified.
