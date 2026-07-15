from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import unittest

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "templates/marker-comment/template.yml"
DOCKERFILE = PROJECT_ROOT / "templates/marker-comment/Dockerfile"
PROCESSOR_COMMAND = PROJECT_ROOT / "templates/marker-comment/marker-comment-process"


def load_template() -> tuple[dict[str, object], dict[str, object]]:
    documents = list(yaml.safe_load_all(TEMPLATE.read_text(encoding="utf-8")))
    if len(documents) != 2:
        raise AssertionError("component template must contain a header and one body")
    return documents[0], documents[1]


def compile_component(
    *,
    job_name: str,
    stage: str,
    version: str,
    file_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> dict[str, object]:
    _, raw_body = load_template()
    job = deepcopy(raw_body["$[[ inputs.job-name ]]"])
    job["stage"] = stage
    job["image"] = job["image"].replace("$[[ component.version ]]", version)
    serialized_globs = {
        "MARKER_COMMENT_FILE_GLOBS": file_globs or [],
        "MARKER_COMMENT_EXCLUDE_GLOBS": exclude_globs or [],
    }
    for variable, patterns in serialized_globs.items():
        job["variables"][variable] = "serialized:" + json.dumps(patterns)
    return {job_name: job}


class PublicComponentContractTests(unittest.TestCase):
    def test_component_declares_the_complete_public_input_contract(self) -> None:
        header, _ = load_template()

        self.assertEqual(header["spec"]["component"], ["version"])
        inputs = header["spec"]["inputs"]
        self.assertEqual(
            set(inputs),
            {
                "marker-text",
                "job-name",
                "stage",
                "fail-when-patch-needed",
                "file-globs",
                "exclude-globs",
                "begin-sentinel",
                "end-sentinel",
            },
        )
        self.assertNotIn("default", inputs["marker-text"])
        self.assertEqual(inputs["marker-text"]["type"], "string")
        self.assertEqual(inputs["job-name"]["default"], "marker-comment")
        self.assertEqual(inputs["stage"]["default"], "test")
        self.assertEqual(inputs["fail-when-patch-needed"]["type"], "boolean")
        self.assertIs(inputs["fail-when-patch-needed"]["default"], True)
        for name in ("file-globs", "exclude-globs"):
            self.assertEqual(inputs[name]["type"], "array")
            self.assertEqual(inputs[name]["default"], [])
        self.assertEqual(inputs["begin-sentinel"]["default"], "MARKER-COMMENT: BEGIN")
        self.assertEqual(inputs["end-sentinel"]["default"], "MARKER-COMMENT: END")

    def test_default_fixture_compiles_to_exactly_one_isolated_mr_job(self) -> None:
        _, raw_body = load_template()
        compiled = compile_component(
            job_name="marker-comment", stage="test", version="1.4.2"
        )

        self.assertEqual(list(compiled), ["marker-comment"])
        job = compiled["marker-comment"]
        self.assertEqual(job["stage"], "test")
        self.assertEqual(
            job["image"],
            "registry.gitlab.com/platform/ci-components/marker-comment:1.4.2",
        )
        self.assertEqual(
            job["rules"],
            [{"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'}],
        )
        self.assertEqual(
            job["variables"],
            {
                "GIT_DEPTH": "0",
                "MARKER_COMMENT_FILE_GLOBS": "serialized:[]",
                "MARKER_COMMENT_EXCLUDE_GLOBS": "serialized:[]",
            },
        )
        self.assertEqual(
            job["artifacts"],
            {
                "when": "always",
                "name": "marker-comment-$CI_COMMIT_SHORT_SHA",
                "paths": ["marker-comment.patch"],
                "expire_in": "1 week",
            },
        )
        self.assertNotIn("stages", raw_body)
        self.assertNotIn("default", raw_body)
        self.assertNotIn("before_script", raw_body)
        self.assertNotIn("after_script", raw_body)
        self.assertNotIn("variables", raw_body)

    def test_custom_fixture_changes_only_the_public_job_name_and_stage(self) -> None:
        compiled = compile_component(
            job_name="policy-marker",
            stage="policy",
            version="2.0.1",
            file_globs=["src/**/*.py", "*.sh"],
            exclude_globs=["vendor/**"],
        )

        self.assertEqual(list(compiled), ["policy-marker"])
        self.assertEqual(compiled["policy-marker"]["stage"], "policy")
        self.assertTrue(
            compiled["policy-marker"]["image"].endswith(":2.0.1")
        )
        self.assertEqual(
            compiled["policy-marker"]["variables"]["MARKER_COMMENT_FILE_GLOBS"],
            'serialized:["src/**/*.py", "*.sh"]',
        )
        self.assertEqual(
            compiled["policy-marker"]["variables"]["MARKER_COMMENT_EXCLUDE_GLOBS"],
            'serialized:["vendor/**"]',
        )

    def test_job_invokes_only_the_image_internal_processor_command(self) -> None:
        _, body = load_template()
        job = body["$[[ inputs.job-name ]]"]

        script = "\n".join(job["script"])
        self.assertIn("marker-comment-process", script)
        self.assertIn('"${MARKER_COMMENT_FILE_GLOBS#serialized:}"', script)
        self.assertIn('"${MARKER_COMMENT_EXCLUDE_GLOBS#serialized:}"', script)
        self.assertNotIn("$[[ inputs.file-globs ]]", script)
        self.assertNotIn("$[[ inputs.exclude-globs ]]", script)
        self.assertNotIn("python", script)
        self.assertNotIn("CI_REGISTRY_IMAGE", job["image"])
        self.assertNotIn("$CI_PROJECT_DIR/", script)

    def test_processor_image_contains_git_and_the_internal_command(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        command = PROCESSOR_COMMAND.read_text(encoding="utf-8")

        self.assertIn("apk add --no-cache git", dockerfile)
        self.assertIn("COPY marker_comment", dockerfile)
        self.assertIn("marker-comment-process", dockerfile)
        self.assertIn("python3 -m marker_comment", command)


if __name__ == "__main__":
    unittest.main()
