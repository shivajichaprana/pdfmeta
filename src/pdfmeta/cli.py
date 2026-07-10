"""Command-line interface for pdfmeta — simple by design.

    view   Show all metadata actually in a PDF (Document Info + XMP).
    run    Apply the JSON metadata from a folder to every PDF in a folder.
    gui    Launch the local browser-based metadata editor.
    scrub  Remove all metadata from a PDF (privacy).
    template  Dump a PDF's metadata as editable JSON.

Typical workflow:

    pdfmeta view input_pdf/report.pdf     # 1. check the current metadata
    pdfmeta run                           # 2. apply input_json/*.json -> output/
    pdfmeta view output/report.pdf        # 3. check the result

Or, for a point-and-click editor:  pdfmeta gui
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .batch import process_folder
from .editor import PDFMetadataEditor, PDFMetadataError

# Default folders for the batch `run` workflow.
DEFAULT_PDF_DIR = "input_pdf"
DEFAULT_JSON_DIR = "input_json"
DEFAULT_OUT_DIR = "output"


def _print_sections(sections: dict[str, dict[str, str]]) -> None:
    """Print `view` output, one titled section per part of the metadata."""
    any_printed = False
    for title, data in sections.items():
        print(f"[{title}]")
        if data:
            width = max(len(k) for k in data)
            for key, value in data.items():
                print(f"  {key.ljust(width)}  {value}")
            any_printed = True
        else:
            print("  (none)")
        print()
    if not any_printed:
        print("(no metadata found in this PDF)")


def _run_gui(port: int, open_browser: bool = True) -> int:
    """Start the local web GUI, opening a browser unless told not to."""
    try:
        from .webapp import create_app
    except ImportError:
        print(
            "The GUI needs Flask, which isn't installed.\n"
            'Install it with:  pip install "pdfmeta[gui]"',
            file=sys.stderr,
        )
        return 1
    import threading
    import webbrowser

    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"pdfmeta GUI running at {url}   (press Ctrl+C to stop)")
    create_app().run(host="127.0.0.1", port=port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfmeta",
        description="View and change PDF metadata.",
    )
    parser.add_argument("--version", action="version", version=f"pdfmeta {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # view — check the metadata actually in a PDF
    p_view = sub.add_parser(
        "view",
        help="Show all metadata actually in a PDF (Document Info + XMP).",
    )
    p_view.add_argument("pdf", help="Path to the PDF file.")
    p_view.add_argument("--json", action="store_true", help="Output as JSON.")

    # run — apply the JSON folder to the PDF folder
    p_run = sub.add_parser(
        "run",
        help="Apply the JSON metadata to every PDF in the input folder.",
        description=(
            "Read PDFs from the input folder, apply the JSON metadata, and "
            "write the results to the output folder. A PDF uses the JSON with "
            "the same name if present, otherwise the single JSON in the folder. "
            "Original PDFs are never modified."
        ),
    )
    p_run.add_argument(
        "--pdf-dir",
        default=DEFAULT_PDF_DIR,
        help=f"Folder of input PDFs (default: {DEFAULT_PDF_DIR}).",
    )
    p_run.add_argument(
        "--json-dir",
        default=DEFAULT_JSON_DIR,
        help=f"Folder of input JSON files (default: {DEFAULT_JSON_DIR}).",
    )
    p_run.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Folder for result PDFs (default: {DEFAULT_OUT_DIR}).",
    )
    p_run.add_argument(
        "--merge",
        action="store_true",
        help="Add/update the JSON fields but keep other existing "
        "metadata (default: replace to match the JSON exactly).",
    )

    # gui — local browser-based editor
    p_gui = sub.add_parser(
        "gui",
        help="Launch the local browser-based metadata editor.",
        description="Open a small web page on this computer to upload a PDF, edit "
        "its metadata tags, and download the result. Nothing leaves "
        "your machine.",
    )
    p_gui.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    p_gui.add_argument(
        "--no-browser", action="store_true", help="Don't open a browser window automatically."
    )

    # scrub — remove all metadata (privacy)
    p_scrub = sub.add_parser(
        "scrub",
        help="Remove ALL metadata from a PDF (Document Info + XMP).",
        description="Strip every metadata tag from a PDF — useful before sharing "
        "a file. Edits in place unless you pass -o to write a clean copy.",
    )
    p_scrub.add_argument("pdf", help="Path to the PDF file.")
    p_scrub.add_argument(
        "-o", "--output", help="Write the cleaned PDF here instead of editing in place."
    )

    # template — dump a PDF's metadata as an editable JSON
    p_tmpl = sub.add_parser(
        "template",
        help="Write a PDF's current metadata as JSON you can edit and reuse.",
        description="Read a PDF's metadata and write it as a JSON file (or print "
        "it). Edit the result and feed it to `run` to apply it to other PDFs.",
    )
    p_tmpl.add_argument("pdf", help="Path to the PDF file.")
    p_tmpl.add_argument(
        "-o", "--output", help="Write the JSON here (default: print to the screen)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "view":
            with PDFMetadataEditor(args.pdf) as editor:
                sections = editor.read_all()
            if args.json:
                print(json.dumps(sections, indent=2, ensure_ascii=False))
            else:
                _print_sections(sections)
            return 0

        if args.command == "run":
            results = process_folder(args.pdf_dir, args.json_dir, args.out_dir, merge=args.merge)
            if not results:
                print(f"No PDF files found in {args.pdf_dir}/.")
                return 0
            ok = 0
            for r in results:
                if r["status"] == "ok":
                    ok += 1
                    print(f"  {r['pdf']}  <-  {r['json']}  ->  {r['output']}")
                else:
                    print(f"  {r['pdf']}  ({r['status']})")
            print(f"\nDone: {ok} of {len(results)} PDF(s) written to {args.out_dir}/.")
            return 0 if ok == len(results) else 1

        if args.command == "scrub":
            with PDFMetadataEditor(args.pdf) as editor:
                editor.clear()
                dest = editor.save(args.output)
            print(f"Removed all metadata -> {dest}")
            return 0

        if args.command == "template":
            with PDFMetadataEditor(args.pdf) as editor:
                if args.output:
                    editor.export_json(args.output)
                    print(f"Wrote metadata template -> {args.output}")
                else:
                    print(json.dumps(editor.read(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "gui":
            return _run_gui(args.port, open_browser=not args.no_browser)

    except PDFMetadataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        return 130

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
