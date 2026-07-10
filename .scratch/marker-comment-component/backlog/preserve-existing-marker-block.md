Title: Support Preserving Existing Marker Blocks
Status: backlog

## Follow-up

Add an opt-in policy that treats a single structurally valid existing Marker Comment Block as compliant without changing its Managed Marker Body or position.

## Initial shape

V1 always overwrites the Managed Marker Body with the canonical configured text and restores the block to the required first safe content position. A future preservation policy should leave the entire valid block untouched while retaining v1's exact, syntax-aware sentinel matching and its errors for malformed, nested, or duplicate markers.
