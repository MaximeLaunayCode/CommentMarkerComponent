fixture=$1
rm -rf "$fixture"
mkdir -p "$fixture"

git -C "$fixture" init --quiet --initial-branch=main
git -C "$fixture" config user.name "Release Fixture"
git -C "$fixture" config user.email "release-fixture@example.test"
printf 'base\n' >"$fixture/base.txt"
git -C "$fixture" add base.txt
git -C "$fixture" commit --quiet -m base
base=$(git -C "$fixture" rev-parse HEAD)
git -C "$fixture" remote add origin .

cp -R tests/fixtures/release-consumer/. "$fixture/"
git -C "$fixture" add .
git -C "$fixture" commit --quiet -m "mixed eligible and excluded files"
head=$(git -C "$fixture" rev-parse HEAD)

export CI_PROJECT_DIR=$fixture
export CI_MERGE_REQUEST_DIFF_BASE_SHA=$base
export CI_MERGE_REQUEST_TARGET_BRANCH_NAME=main
export CI_COMMIT_SHA=$head
export CI_COMMIT_SHORT_SHA=$(git -C "$fixture" rev-parse --short HEAD)
