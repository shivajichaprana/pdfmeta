# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Double-click launchers (`Open pdfmeta editor.command` for macOS and a `.bat`
  for Windows) that set up and open the browser editor with no terminal use.
- `scrub` command — remove all metadata (Document Info + XMP) from a PDF, in
  place or to a clean copy (`-o`). Handy before sharing a file.
- `template` command — dump a PDF's current metadata as editable JSON (to a
  file or the screen), so you can tweak it and feed it to `run`.
- The browser GUI now edits the known XMP fields (`copyright`, `language`,
  `rating`, …) as well as Document Info, so it can change everything `view`
  shows.
- The browser GUI gained: drag-and-drop upload, a one-click "Remove all
  metadata" button, a read-only view of other tools' XMP tags (nothing hidden),
  and a batch mode to tag many PDFs at once and download them as a zip.
- GUI polish: automatic dark mode, keyboard focus styles, and button feedback
  that prevents double-submits.
- GUI: a Quit button that stops the local server (no need to find the
  terminal), a "preparing your download" confirmation, and a favicon.
- GUI security: the local server only accepts requests addressed to
  localhost (defeats DNS-rebinding) and rejects cross-origin POSTs (CSRF), so a
  website you visit can't reach the editor while it runs.
- Property-based tests (Hypothesis) fuzzing the date parser and the metadata
  round-trip.
- Developer tooling and quality gates: Ruff (lint + format), strict mypy
  type-checking, and test coverage. CI now runs lint, type-check, and the test
  suite across Python 3.9–3.13 on Linux, macOS, and Windows, with pip caching.
- Automated PyPI release workflow (on `v*` tags, via trusted publishing).
- CodeQL security scanning and an OpenSSF Scorecard workflow with a badge.
- Community health files: `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue and PR
  templates, Dependabot, a pre-commit config, and `.editorconfig`.

### Changed
- Modernized type annotations throughout; the package type-checks under mypy
  `--strict`.

## [0.1.0] - 2026-07-10

Initial release.

### Commands
- `pdfmeta view <pdf>` — show every metadata tag actually in a PDF: the complete
  Document Information dictionary and every XMP property, read directly with no
  filtering or guessing (including tags written by other tools). `--json` for
  machine-readable output.
- `pdfmeta run` — batch: apply the JSON metadata in `input_json/` to every PDF in
  `input_pdf/`, writing results to `output/`. Uses a same-named JSON per PDF or
  the single JSON for all; `--merge` keeps other metadata (default replaces to
  match the JSON exactly); `--pdf-dir` / `--json-dir` / `--out-dir` override the
  folders. Originals are never modified.
- `pdfmeta gui` — a local browser editor to upload a PDF, edit its tags, and
  download the result. Requires the optional `gui` extra
  (`pip install "pdfmeta[gui]"`); runs entirely on your machine.

### Library
- `PDFMetadataEditor` engine: read/set/remove/clear metadata, `apply_json`,
  `import_json`, `export_json`, `replace_docinfo`, `read_all`, and `xmp_packet`.
- Standard fields are mirrored into the XMP stream so every viewer stays
  consistent. Creation/modification dates accept friendly formats, ISO 8601,
  existing PDF `D:` dates, or `now`. The `Trapped` flag is stored as a PDF name.
- Rich XMP fields: `copyright`, `rights-marked`, `license`, `usage-terms`,
  `owner`, `language`, `publisher`, `contributor`, `rating`, `label`,
  `metadata-date`, `document-id`, `instance-id`, `pdfa-part`, `pdfa-conformance`,
  plus arbitrary custom fields.

### Robustness
- Editing one field never wipes pre-existing metadata (XMP is written with
  `update_docinfo=False`).
- `run` refuses to overwrite originals (output folder same as input) and matches
  `.pdf` / `.PDF` case-insensitively.
- Invalid/missing/malformed JSON and corrupt PDFs produce clear errors; one bad
  file in a batch never stops the rest.

### Packaging
- `src/` layout, `python -m pdfmeta` entry point, PEP 561 `py.typed` marker, and
  GitHub Actions CI across Python 3.9–3.13.

[Unreleased]: https://github.com/shivajichaprana/pdfmeta/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/shivajichaprana/pdfmeta/releases/tag/v0.1.0
