from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE = PROJECT_ROOT / ".gitlab-ci.yml"
README = PROJECT_ROOT / "README.md"
CONSUMER_PIPELINE = PROJECT_ROOT / "examples/consumer/.gitlab-ci.yml"
FIXTURE = PROJECT_ROOT / "tests/fixtures/release-consumer"
COMPONENT_TEMPLATE = PROJECT_ROOT / "templates/marker-comment/template.yml"


class ReleaseContractTests(unittest.TestCase):
    def test_release_pipeline_builds_and_releases_one_semantic_version(self) -> None:
        pipeline = yaml.safe_load(PIPELINE.read_text(encoding="utf-8"))

        self.assertEqual(pipeline["stages"], ["test", "build", "integration", "release"])
        image_job = pipeline["build-processor-image"]
        image_script = "\n".join(image_job["script"])
        self.assertIn("$CI_REGISTRY_IMAGE/marker-comment:$CI_COMMIT_SHA", image_script)
        self.assertIn("$CI_REGISTRY_IMAGE/marker-comment:$CI_COMMIT_TAG", image_script)
        self.assertIn("docker push", image_script)

        release_job = pipeline["publish-component-release"]
        self.assertEqual(release_job["stage"], "release")
        self.assertIn("$CI_COMMIT_TAG", release_job["release"]["tag_name"])
        self.assertIn("$CI_COMMIT_TAG", release_job["release"]["description"])
        self.assertEqual(
            release_job["needs"],
            [
                "unit-tests",
                "component-lint",
                "consumer-fixture-tests",
                "build-processor-image",
                "tagged-component-e2e",
                "sample-consumer-pipeline",
            ],
        )

        rendered = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("CI_COMMIT_TAG =~", rendered)
        self.assertIn("marker-comment@$CI_COMMIT_SHA", rendered)
        self.assertIn("component-lint", rendered)
        tagged_include = pipeline["include"][1]
        self.assertEqual(
            tagged_include["component"],
            "$CI_SERVER_FQDN/$CI_PROJECT_PATH/marker-comment@$CI_COMMIT_TAG",
        )
        self.assertEqual(tagged_include["inputs"]["job-name"], "tagged-component-e2e")

        sample_job = pipeline["sample-consumer-pipeline"]
        self.assertEqual(
            sample_job["image"],
            "$CI_REGISTRY_IMAGE/marker-comment:$CI_COMMIT_TAG",
        )
        self.assertEqual(sample_job["needs"][0]["job"], "tagged-component-e2e")

    def test_readme_and_consumer_example_cover_the_operating_contract(self) -> None:
        readme = README.read_text(encoding="utf-8")
        for required in (
            "marker-text",
            "job-name",
            "fail-when-patch-needed",
            "file-globs",
            "exclude-globs",
            "begin-sentinel",
            "end-sentinel",
            "Hash line",
            "Slash line",
            "Bang line",
            "HTML block",
            "CSS block",
            "Git-wildmatch",
            "Built-in exclusions",
            "Exit codes",
            "marker-comment.patch",
            "git apply --check",
            "commit",
            "push",
            "merge request pipelines",
            "full, fetchable history",
            "fork merge requests",
            "V1 boundaries",
            "does not commit or push",
            "no API token",
        ):
            self.assertIn(required.lower(), readme.lower())

        consumer = yaml.safe_load(CONSUMER_PIPELINE.read_text(encoding="utf-8"))
        self.assertIn("workflow", consumer)
        component = consumer["include"][0]["component"]
        self.assertRegex(component, r"@\d+\.\d+\.\d+$")
        self.assertNotIn("@main", component)
        self.assertNotIn("@~latest", component)

    def test_released_component_has_no_write_or_api_credentials_contract(self) -> None:
        header, component = list(
            yaml.safe_load_all(COMPONENT_TEMPLATE.read_text(encoding="utf-8"))
        )

        self.assertFalse(
            any("token" in input_name.lower() for input_name in header["spec"]["inputs"])
        )
        script = "\n".join(component["$[[ inputs.job-name ]]"]["script"]).lower()
        for forbidden in ("git commit", "git push", "private-token", "job-token", "curl"):
            self.assertNotIn(forbidden, script)


class TaggedConsumerEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        subprocess.run(
            ["sh", "tests/fixtures/setup-release-fixture.sh", str(self.repository)],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.base = self.git("rev-list", "--max-parents=0", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def run_processor(self) -> subprocess.CompletedProcess[str]:
        head = self.git("rev-parse", "HEAD").stdout.strip()
        environment = os.environ.copy()
        processor_command = os.environ.get("MARKER_COMMENT_PROCESSOR_COMMAND")
        environment.update(
            {
                "CI_PROJECT_DIR": str(self.repository),
                "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.base,
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
                "CI_COMMIT_SHA": head,
                "CI_COMMIT_SHORT_SHA": head[:8],
            }
        )
        if processor_command:
            environment.pop("PYTHONPATH", None)
            command = shlex.split(processor_command)
        else:
            environment["PYTHONPATH"] = str(PROJECT_ROOT)
            command = [sys.executable, "-m", "marker_comment"]
        return subprocess.run(
            [*command, "--marker-text", "Managed by release 1.0.0"],
            cwd=self.repository,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_tagged_workflow_patch_applies_and_reruns_without_an_artifact(self) -> None:
        _, component = list(
            yaml.safe_load_all(COMPONENT_TEMPLATE.read_text(encoding="utf-8"))
        )
        tagged_image = component["$[[ inputs.job-name ]]"]["image"].replace(
            "$[[ component.version ]]", "1.0.0"
        )
        self.assertEqual(
            tagged_image,
            "registry.gitlab.com/platform/ci-components/marker-comment:1.0.0",
        )

        patch_needed_run = self.run_processor()

        self.assertEqual(patch_needed_run.returncode, 1, patch_needed_run.stdout)
        self.assertIn("src/check.py", patch_needed_run.stdout)
        self.assertIn("vendor/ignored.py", patch_needed_run.stdout)
        patch = self.repository / "marker-comment.patch"
        patch_bytes = patch.read_bytes()
        self.assertTrue(patch_bytes)

        self.git("reset", "--hard", "HEAD")
        patch.write_bytes(patch_bytes)
        apply_check = self.git("apply", "--check", "marker-comment.patch", check=False)
        self.assertEqual(apply_check.returncode, 0, apply_check.stderr)
        self.git("apply", "marker-comment.patch")
        patch.unlink()
        self.git("add", "src/check.py")
        self.git("commit", "--quiet", "-m", "apply marker comment patch")

        clean_rerun = self.run_processor()

        self.assertEqual(clean_rerun.returncode, 0, clean_rerun.stdout)
        self.assertIn("No Marker Comment Block changes needed.", clean_rerun.stdout)
        self.assertFalse(patch.exists())
        self.assertEqual(
            (self.repository / "vendor/ignored.py").read_text(encoding="utf-8"),
            "print('excluded')\n",
        )


if __name__ == "__main__":
    unittest.main()
