# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- A local browser GUI (`pdfmeta gui`): upload a PDF, edit its metadata tags in a
  table (add / change / delete), and download the result — all on your own
  machine. Requires the optional `gui` extra (`pip install "pdfmeta[gui]"`).

### Changed
- Simplified the command-line tool to two focused commands: `view` (show all
  metadata actually in a PDF) and `run` (apply the JSON folder to the PDF
  folder). The single-file `set`/`remove`/`clear`/`apply`/`export`/`import`/
  `fields` subcommands were removed from the CLI; that functionality remains
  available through the `PDFMetadataEditor` library API.
- `view` now shows the complete metadata (Document Info + every XMP property) by
  default; the old `--all` / `--raw` flags are no longer needed.

### Hardened
- `import_json` reports missing files, unreadable files, invalid JSON, and
  wrong-shaped JSON as clear errors instead of raw exceptions.
- The batch `run` never stops on a single bad file: a corrupt or unreadable PDF
  is reported and skipped while the rest are processed. Clear errors for empty
  folders and a missing JSON file.

### Added
- `view --all` shows every tag actually in the file: the complete Document
  Information dictionary plus every XMP property (including tags from other
  tools, not just the ones pdfmeta sets), read directly with no assumptions.
  `view --raw` prints the literal XMP XML packet.
- Batch folder workflow: a `run` command (and `pdfmeta.batch.process_folder`)
  that applies JSON metadata to every PDF in `input_pdf/`, using a same-named
  JSON or the single JSON in `input_json/`, and writes results to `output/`.
  Supports `--merge` and custom `--pdf-dir` / `--json-dir` / `--out-dir`.
- Moved to a `src/` layout with `examples/` samples and dedicated batch folders.
- `apply` command and `PDFMetadataEditor.apply_json()` — replace a PDF's
  metadata with exactly the fields from a JSON file, removing any extras. The
  CLI accepts the PDF and JSON arguments in either order.
- Editing the creation and modification dates (`/CreationDate`, `/ModDate`)
  with friendly `created` / `modified` aliases. Accepts plain dates, ISO 8601,
  existing PDF `D:` dates, or `now`, and mirrors the value into XMP
  (`xmp:CreateDate` / `xmp:ModifyDate`).
- Proper editing of the `Trapped` flag as a PDF name (`/True`, `/False`,
  `/Unknown`).
- A set of rich XMP fields: `copyright`, `rights-marked`, `license`,
  `usage-terms`, `owner`, `language`, `publisher`, `contributor`, `rating`,
  `label`, `metadata-date`, `document-id`, `instance-id`, `pdfa-part`, and
  `pdfa-conformance`, with type-aware handling (arrays, booleans, dates) and
  convenient aliases.
- `pdfmeta fields` command listing every field name the tool understands.

## [0.1.0] - 2026-07-10

### Added
- `PDFMetadataEditor` library class to read, set, remove, and clear PDF
  metadata, plus JSON import/export.
- Support for arbitrary custom metadata fields alongside the standard
  Title/Author/Subject/Keywords/Creator/Producer fields.
- XMP metadata stream kept in sync for standard fields.
- `pdfmeta` command-line interface with `view`, `set`, `remove`, `clear`,
  `export`, and `import` subcommands.
- `python -m pdfmeta` entry point.
- PEP 561 `py.typed` marker so downstream users get the type hints.
- pytest test suite and GitHub Actions CI across Python 3.9–3.13.

[Unreleased]: https://github.com/shivajichaprana/pdfmeta/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/shivajichaprana/pdfmeta/releases/tag/v0.1.0
