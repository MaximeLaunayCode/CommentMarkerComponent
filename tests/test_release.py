from __future__ import annotations

import os
from pathlib import Path
import shutil
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
            ["unit-tests", "component-lint", "build-processor-image", "release-e2e"],
        )

        rendered = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("CI_COMMIT_TAG =~", rendered)
        self.assertIn("marker-comment@$CI_COMMIT_SHA", rendered)
        self.assertIn("component-lint", rendered)
        self.assertEqual(
            pipeline["release-e2e"]["image"],
            "$CI_REGISTRY_IMAGE/marker-comment:$CI_COMMIT_SHA",
        )

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


class TaggedConsumerEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Release Fixture")
        self.git("config", "user.email", "release-fixture@example.test")
        (self.repository / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "--quiet", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("remote", "add", "origin", ".")
        shutil.copytree(FIXTURE, self.repository, dirs_exist_ok=True)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "mixed eligible and excluded files")

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
        environment.update(
            {
                "CI_PROJECT_DIR": str(self.repository),
                "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.base,
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
                "CI_COMMIT_SHA": head,
                "CI_COMMIT_SHORT_SHA": head[:8],
                "PYTHONPATH": str(PROJECT_ROOT),
            }
        )
        return subprocess.run(
            [sys.executable, "-m", "marker_comment", "--marker-text", "Managed by release 1.0.0"],
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

        first = self.run_processor()

        self.assertEqual(first.returncode, 1, first.stdout)
        self.assertIn("src/check.py", first.stdout)
        self.assertIn("vendor/ignored.py", first.stdout)
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

        second = self.run_processor()

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("No Marker Comment Block changes needed.", second.stdout)
        self.assertFalse(patch.exists())
        self.assertEqual(
            (self.repository / "vendor/ignored.py").read_text(encoding="utf-8"),
            "print('excluded')\n",
        )


if __name__ == "__main__":
    unittest.main()
