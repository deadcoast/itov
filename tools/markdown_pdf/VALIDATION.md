# Local verification - 2026-09-21

Verified on Windows with Python 3.13.9 and the committed tool lockfile.

- Converter suite: **12 passed, 1 skipped**. This host cannot create symbolic links;
  the separate real Windows junction-pruning test passed.
- Ruff lint and formatting checks passed. Git whitespace checks passed.
- The real PowerShell prompt accepted a directory and completed discovery. Supplying
  a positional directory bypassed the prompt. The launcher also worked when called by
  absolute path from another working directory.
- Exported `docs/design_spec` to `output/pdf/itov-design-specs.pdf`: **17 documents,
  266 pages, 17 PDF bookmarks**. `scene_templates/sensitive` was pruned before descent.
- Extracted PDF text contains all **10,480 code lines across 192 code blocks**, comparing
  with whitespace removed to accommodate PDF line wrapping. This is text-preservation
  evidence, not a byte-for-byte round-trip guarantee.
- Checked text bounds on every page: zero spans outside the margins. Rendered-page
  review covered the index, document transitions, code, tables, and conversion notes;
  heading pagination was corrected after review.
- The only formatting warning for the real export was a wide table converted to labeled
  row records. No unsupported-glyph warnings remained for this source set.
- Synthetic export checks also covered inline HTML, footnotes, internal/external links,
  nested/task lists, long code lines, multipage code, very tall table rows, empty files,
  encoding errors, overwrite protection, and temporary-file cleanup after failure.

An initial test run could not access an existing `.test-tmp` directory; rerunning in a
new repository-local temporary directory resolved the harness error. Initial testing
also exposed unresolved footnote anchors and an open temporary stream on PDF failure;
both were repaired and are covered by the passing tests.

Linux/macOS and ingestion by an external LLM were not tested. The filename exclusions
are not content classification, and no external upload-policy acceptance is claimed.
