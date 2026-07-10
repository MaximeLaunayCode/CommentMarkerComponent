Title: Decide File Exclusions
Type: grilling
Status: resolved

## Question

Which MR-added files should v1 ignore even if they are text files, and how should consumers configure exclusions?

## Expected answer

Decide defaults for generated files, lockfiles, vendored files, binary files, large files, hidden files, and configurable include/exclude patterns.

## Answer

V1 starts from a published, case-sensitive default allowlist. An MR-Added File is eligible by default when it has one of these extensions or special names:

- Hash-line comments: `.sh`, `.bash`, `.zsh`, `.ksh`, `.fish`, `.py`, `.rb`, `.yml`, `.yaml`, and `.toml`.
- Slash-line comments: `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.java`, `.c`, `.h`, `.cc`, `.cpp`, `.cxx`, `.hpp`, `.cs`, `.go`, `.kt`, `.kts`, `.swift`, and `.rs`.
- Bang-line comments for modern free-form Fortran: `.f90`, `.f95`, `.f03`, `.f08`, and `.f18`. Legacy fixed-form `.f`, `.for`, and `.ftn` files are not eligible by default.
- HTML comments: `.html`, `.htm`, `.xml`, `.md`, `.markdown`, `.vue`, and `.svelte`.
- CSS block comments: `.css`, `.scss`, `.sass`, and `.less`.
- Special build filenames: `Dockerfile`, `Dockerfile.*`, `Makefile`, `GNUmakefile`, and `*.mk`.

Everything outside this default allowlist is an Excluded MR-Added File. The component also applies these built-in exclusions after the allowlist:

- Any path containing a dot-prefixed segment, including a dotfile or a file below a hidden directory.
- Exact lockfile basenames: `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lock`, `bun.lockb`, `Cargo.lock`, `Gemfile.lock`, `poetry.lock`, `uv.lock`, `Pipfile.lock`, `composer.lock`, `go.sum`, `gradle.lockfile`, `packages.lock.json`, `Podfile.lock`, `mix.lock`, `pubspec.lock`, and `flake.lock`.
- Any path containing an exact vendored-directory segment named `vendor`, `vendors`, `third_party`, `third-party`, `node_modules`, or `bower_components`.
- Files containing a NUL byte, which v1 treats as binary.
- Symlinks and Git submodule entries; only regular files are processed.

V1 has no file-size exclusion. It also does not guess whether a file is generated. Consumers should identify their generated paths with `exclude-globs`.

`file-globs` and `exclude-globs` are array inputs matching repository-relative paths with documented Git-style `/`, `*`, `?`, `**`, and character-class semantics. A non-empty `file-globs` narrows the default allowlist; `exclude-globs` adds to the built-in exclusions; an exclusion always wins. Invalid patterns are configuration errors: the job names the offending pattern and fails before modifying files or creating a patch.

The job prints one sorted `Excluded MR-Added Files` section with one path and inline exclusion reason per entry; reasons do not need separate groups. If no Eligible MR-Added Files remain, the job prints that fact, succeeds, and creates no patch artifact.
