# Glossary

## Marker Comment Block

The configured block of comment lines inserted into each newly added file by the GitLab CI Component. It carries the configured text string and must be distinguishable from the file's existing content.

## Managed Marker Body

The content enclosed by a Marker Comment Block's configured begin and end sentinels.

## MR-Added File

A file whose merge request diff status is added when compared with the merge request target branch. The component targets these files rather than files added by each individual commit.

## Eligible MR-Added File

An MR-Added File selected for Marker Comment Block processing because it matches the component's effective include patterns and no exclusion.

## Excluded MR-Added File

An MR-Added File intentionally left unchanged because it matches a built-in or consumer-configured exclusion. The component reports these files in a dedicated job-log section.

## Report-Only Mode

A component mode that reports needed Marker Comment Block changes without making those changes alone fail the job. Discovery, configuration, and malformed-marker errors still fail the job.
