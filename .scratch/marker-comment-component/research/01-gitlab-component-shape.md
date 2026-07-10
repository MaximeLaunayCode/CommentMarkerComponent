# Research: GitLab CI Component Shape

## Sources

- GitLab CI/CD components: https://docs.gitlab.com/ci/components/
- GitLab CI/CD component examples: https://docs.gitlab.com/ci/components/examples/
- GitLab CI/CD YAML syntax reference, `spec:inputs`: https://docs.gitlab.com/ci/yaml/#specinputs
- GitLab include components: https://docs.gitlab.com/ci/yaml/includes/#includecomponent

## Relevant GitLab Rules

GitLab CI/CD components are reusable pipeline configuration units. Consumers include them with:

```yaml
include:
  - component: $CI_SERVER_FQDN/<group>/<project>/<component>@<version>
    inputs:
      stage: test
```

The component project should contain:

- `README.md` documenting the component and at least one usage example.
- `LICENSE.md`.
- `.gitlab-ci.yml` that tests the component and creates releases.
- A top-level `templates/` directory.

Each component can be either a single file, such as `templates/marker-comment.yml`, or a directory containing `template.yml`, such as `templates/marker-comment/template.yml`. Directory form is better here because this component will need component-specific docs, test fixtures, and likely a release image later. Only `template.yml` is the public component configuration; colocated helper files are useful for tests/builds but should not be assumed to exist in consuming projects.

The component header should use `spec:inputs` rather than custom CI variables for normal configuration. Inputs support defaults, descriptions, validation with options/regex, and non-string types. Inputs without defaults are mandatory, so v1 should default everything except the marker text if the product wants an explicit consumer decision.

GitLab recommends avoiding global keywords in components because included configuration merges into the consuming pipeline. Jobs and hidden templates should use unique names, and the public job name or prefix should be configurable to avoid collisions.

For portability, use predefined variables such as `$CI_SERVER_FQDN` and `$CI_API_V4_URL` instead of hardcoding a GitLab host or API URL. If the component needs API authentication beyond `CI_JOB_TOKEN`, expose the token variable name as an input or document the required variable, but do not accept secret values as plain inputs.

Catalog publication is release-based. Consumers can pin a commit, branch, or tag, but published catalog releases require semantic version tags. Production examples should pin a semantic version or a compatible partial version rather than `~latest`.

## Recommended V1 Layout

```text
.
|-- .gitlab-ci.yml
|-- LICENSE.md
|-- README.md
|-- templates/
|   `-- marker-comment/
|       |-- template.yml
|       `-- docs.md
`-- test/
    |-- fixtures/
    `-- expected/
```

`templates/marker-comment/template.yml` should define exactly one public job for v1. It should be self-contained enough to run in a consuming repo. If the marker logic becomes too large for maintainable inline shell, the release pipeline should build a versioned image and the template should use component context to reference the matching image tag.

Recommended job strategy:

- One job named from an input, defaulting to `marker-comment`.
- `rules` limited to merge request pipelines.
- No global `stages`, `default`, `variables`, `before_script`, or `after_script`.
- Explicit `image` on the job.
- `artifacts:when: on_failure` for the generated patch because v1 intentionally fails when changes are needed.
- Use `$CI_API_V4_URL` for GitLab API calls and `$CI_JOB_TOKEN` first unless later MR diff research proves it insufficient.

## Recommended Inputs

```yaml
spec:
  inputs:
    job-name:
      default: marker-comment
      description: GitLab CI job name to add to the consuming pipeline.
    stage:
      default: test
      description: Stage where the marker comment check runs.
    marker-text:
      description: Text to place inside the Marker Comment Block.
    patch-path:
      default: marker-comment.patch
      description: Path for the generated patch artifact.
    fail-when-patch-needed:
      type: boolean
      default: true
      description: Fail the job when Marker Comment Block changes are needed.
    file-globs:
      type: array
      default: []
      description: Optional include globs for MR-Added Files; empty means all supported files.
    exclude-globs:
      type: array
      default: []
      description: Optional exclude globs for MR-Added Files.
    api-token-variable:
      default: CI_JOB_TOKEN
      description: Variable name containing the token used for GitLab API calls.
---
"$[[ inputs.job-name ]]":
  stage: $[[ inputs.stage ]]
  image: alpine:3.20
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - echo "Marker comment implementation goes here"
  artifacts:
    when: on_failure
    paths:
      - $[[ inputs.patch-path ]]
```

Input notes:

- `marker-text` should stay mandatory unless a later product decision chooses a generic default. The marker itself is the point of the component, so an implicit default risks silent misuse.
- `file-globs` and `exclude-globs` are included as shape placeholders, but [Decide File Exclusions](../issues/05-decide-file-exclusions.md) owns their exact semantics.
- `fail-when-patch-needed` gives a clean path for report-only behavior if the map keeps it in v1, but [Decide Patch Artifact UX](../issues/06-decide-patch-artifact-ux.md) owns whether v1 actually exposes it.
- The default `image` should be revisited after MR diff and implementation-shape decisions. If inline shell remains small, `alpine` plus installed packages may be enough. If logic grows, use a released component image.

## Minimal Consuming Project Example

```yaml
stages:
  - test

include:
  - component: $CI_SERVER_FQDN/platform/ci-components/marker-comment@1.0.0
    inputs:
      stage: test
      marker-text: "Generated by internal platform policy"
      patch-path: marker-comment.patch
```

When the job detects missing or stale Marker Comment Blocks in MR-Added Files, it should write `marker-comment.patch`, upload it as an artifact, and fail with instructions to apply the patch locally.

## Decision

Use a single GitLab CI Component named `marker-comment`, published from `templates/marker-comment/template.yml`, configured primarily through `spec:inputs`, and documented with top-level and component-specific README content. Keep the v1 template MR-only and patch-only. Do not rely on helper scripts being available in consuming projects; either keep the job script inline for v1 or use a versioned image built by the component project release pipeline.
