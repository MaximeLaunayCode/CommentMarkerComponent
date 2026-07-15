#!/bin/sh
set -eu

source_root=$PWD
patch=$source_root/$1
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT

. "$source_root/tests/fixtures/setup-release-fixture.sh" "$fixture"

git -C "$fixture" apply --check "$patch"
git -C "$fixture" apply "$patch"
git -C "$fixture" add src/check.py
git -C "$fixture" commit --quiet -m "apply marker comment patch"
CI_COMMIT_SHA=$(git -C "$fixture" rev-parse HEAD)
CI_COMMIT_SHORT_SHA=$(git -C "$fixture" rev-parse --short HEAD)
export CI_COMMIT_SHA CI_COMMIT_SHORT_SHA

marker-comment-process \
  --marker-text "Managed by semantic release" \
  --fail-when-patch-needed true \
  --file-globs '[]' \
  --exclude-globs '[]' \
  --begin-sentinel 'MARKER-COMMENT: BEGIN' \
  --end-sentinel 'MARKER-COMMENT: END'

test ! -e "$fixture/marker-comment.patch"
