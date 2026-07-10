Title: Support Automatic Commit and Push Strategy
Status: backlog

## Follow-up

Add a future write strategy that modifies files, commits the marker comment block changes, and pushes back to the merge request source branch.

## Initial shape

This should remain opt-in because it requires repository write credentials, needs loop-prevention behavior, and may interact with protected branches and fork merge requests.
