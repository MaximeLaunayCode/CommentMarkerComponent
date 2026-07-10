Title: Decide Idempotency and Existing Markers
Type: grilling
Status: resolved

## Question

How should the component detect that a marker comment block is already present, and what should it do when a file has a stale, partial, or manually modified marker?

## Expected answer

Define the marker boundaries or matching rules, whether the component updates existing markers, and the behavior for malformed or duplicate markers.

## Answer

V1 identifies an existing Marker Comment Block by exact, syntax-aware matching of the configured begin and end sentinel labels. Both sentinels must use the comment syntax expected for the file, the begin sentinel must precede the end sentinel, and together they must form exactly one structurally valid block. The configured body text is not part of the block's identity.

V1 always uses overwrite behavior. The sentinels are ownership boundaries: the component replaces the entire Managed Marker Body with the current canonical rendering. It also moves the block to the required first safe content position when necessary. Allowing consumers to preserve an existing block is deferred to [Support Preserving Existing Marker Blocks](../backlog/preserve-existing-marker-block.md).

The component must not guess or rewrite a file containing malformed or ambiguous marker structure. Errors include a lone begin or end sentinel, reversed sentinels, nested markers, and more than one complete Marker Comment Block. It should leave each affected file unchanged, continue processing other files, produce patches for valid files, list all marker errors clearly, and fail the job.

Configured sentinel labels define marker identity. If a consumer changes those labels, a block using the previous labels is ordinary file content and the component inserts a new block using the current labels. V1 does not support automatic sentinel migration.
