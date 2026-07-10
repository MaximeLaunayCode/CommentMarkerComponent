Title: Decide Marker Comment Syntax
Type: grilling
Status: resolved

## Question

How should the marker comment block be rendered across supported file types, and what should v1 do for files whose comment syntax is unknown?

## Expected answer

Decide the supported file type set, the comment syntax mapping, where the block is inserted, how multiline configured text is represented, and whether unsupported files are skipped or cause failure.

## Answer

V1 uses a default include allowlist as an input gate. Only MR-Added Files whose filename or extension has a deterministic supported comment-syntax mapping are eligible by default. Files outside that allowlist are Excluded MR-Added Files: the job leaves them unchanged and reports them in its dedicated exclusion log section rather than treating them as errors. Consumers can adjust eligibility through the `file-globs` input.

Comment syntax is determined with deterministic filename and extension mapping. V1 should not use content sniffing beyond preserving known leading syntax-sensitive lines during insertion. Common special filenames such as `Dockerfile`, `Makefile`, `.gitignore`, `.env`, and GitLab CI YAML should be mapped explicitly.

V1 should support these comment syntax families:

- Hash-line comments with `#`, for shell, Python, Ruby, YAML, TOML, `.env`, Dockerfile, Makefile, and Git config-style files.
- Slash-line comments with `//`, for JavaScript, TypeScript, Java, C, C++, C#, Go, Kotlin, Swift, and Rust.
- Bang-line comments with `!`, for modern free-form Fortran (`.f90`, `.f95`, `.f03`, `.f08`, and `.f18`). Legacy fixed-form Fortran is outside the v1 default allowlist.
- HTML comments with `<!-- ... -->`, for HTML, XML, Markdown, Vue, and Svelte markup sections.
- CSS block comments with `/* ... */`, for CSS, SCSS, Sass, and Less.

The Marker Comment Block should be inserted at the first safe content position:

- Preserve a leading shebang as the first line, then insert the block after it.
- Preserve an XML declaration such as `<?xml version="1.0"?>`, then insert the block after it.
- Otherwise insert the block at the top of the file.

Configured marker text should be normalized into logical lines. Trim trailing whitespace per line, but preserve blank lines inside the configured text as blank comment lines. Render each logical line as a separate comment line inside the Marker Comment Block.

Rendered Marker Comment Blocks should include explicit begin and end sentinel lines. The sentinel label text should be user-configurable, with defaults:

```text
MARKER-COMMENT: BEGIN
MARKER-COMMENT: END
```

The begin and end sentinel labels must remain distinct after comment syntax is applied. Line-comment syntaxes render sentinels as ordinary comment lines:

```text
# MARKER-COMMENT: BEGIN
# configured text
# MARKER-COMMENT: END
```

Block-comment syntaxes render the whole Marker Comment Block as a single syntactically valid block comment, with the sentinel labels visible on the opening and closing lines:

```text
/* MARKER-COMMENT: BEGIN
 * configured text
 * second line
 * MARKER-COMMENT: END */
```

For HTML-style comments:

```text
<!-- MARKER-COMMENT: BEGIN
     configured text
     second line
     MARKER-COMMENT: END -->
```

Files without supported comment syntax are Excluded MR-Added Files. V1 leaves them unchanged and reports them with their exclusion reason; their presence alone does not fail the job. This rule was clarified by the later [Decide File Exclusions](05-decide-file-exclusions.md) decision.
