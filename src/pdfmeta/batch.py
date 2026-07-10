"""Batch folder workflow: apply JSON metadata to a whole folder of PDFs.

Drop PDFs in one folder and JSON metadata files in another; ``process_folder``
writes an edited copy of each PDF to an output folder, leaving the originals
untouched.

Which JSON is used for a given PDF:

1. If a JSON with the same base name exists (``report.pdf`` -> ``report.json``),
   that one is used — this lets you give each PDF its own metadata.
2. Otherwise, if the JSON folder contains exactly one JSON file, that single
   file is applied to every PDF — handy for stamping the same metadata onto a
   batch.
3. Otherwise the PDF is skipped and reported, so nothing is guessed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

from .editor import PDFMetadataEditor, PDFMetadataError


def _list_by_suffix(folder: Path, suffix: str) -> List[Path]:
    """Return files in ``folder`` whose extension matches ``suffix``, case-
    insensitively (so ``.PDF`` and ``.pdf`` are both found on every OS)."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == suffix
    )


def _pick_json(pdf: Path, json_files: List[Path]) -> Optional[Path]:
    """Choose the JSON file to apply to ``pdf`` (see module docstring)."""
    same_name = pdf.stem + ".json"
    for jf in json_files:
        if jf.name == same_name:
            return jf
    if len(json_files) == 1:
        return json_files[0]
    return None


def process_folder(
    pdf_dir: Union[str, Path],
    json_dir: Union[str, Path],
    out_dir: Union[str, Path],
    merge: bool = False,
) -> List[Dict[str, Optional[str]]]:
    """Apply JSON metadata to every PDF in ``pdf_dir``.

    Each result is written to ``out_dir`` under the same file name; the input
    PDFs are never modified. With ``merge=False`` (the default) each PDF's
    metadata is replaced to match its JSON exactly; with ``merge=True`` the JSON
    fields are added/updated and any other existing metadata is kept.

    Returns a list of per-file result records, each a dict with keys
    ``pdf``, ``json``, ``output`` and ``status``.
    """
    pdf_dir = Path(pdf_dir)
    json_dir = Path(json_dir)
    out_dir = Path(out_dir)

    if not pdf_dir.is_dir():
        raise PDFMetadataError(f"Input PDF folder not found: {pdf_dir}")
    if not json_dir.is_dir():
        raise PDFMetadataError(f"Input JSON folder not found: {json_dir}")

    pdfs = _list_by_suffix(pdf_dir, ".pdf")
    if not pdfs:
        return []  # nothing to do; caller reports "no PDFs"
    json_files = _list_by_suffix(json_dir, ".json")
    if not json_files:
        raise PDFMetadataError(
            f"No .json metadata file found in {json_dir}. Put one JSON file "
            "there to apply to every PDF, or a name.json matching each PDF."
        )

    # Resolve the output directory only after the inputs check out.
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PDFMetadataError(f"Could not create output folder {out_dir}: {exc}") from exc

    results: List[Dict[str, Optional[str]]] = []
    seen_outputs: Dict[str, str] = {}  # guards against clobbering within a run
    for pdf in pdfs:
        json_file = _pick_json(pdf, json_files)
        if json_file is None:
            results.append(
                {"pdf": pdf.name, "json": None, "output": None,
                 "status": "skipped: no matching JSON (several JSON files, none named "
                           f"{pdf.stem}.json)"}
            )
            continue
        out_path = out_dir / pdf.name
        # Never write onto the original input file.
        if out_path.resolve() == pdf.resolve():
            results.append(
                {"pdf": pdf.name, "json": json_file.name, "output": None,
                 "status": "error: output path is the same as the input; refusing "
                           "to overwrite the original (use a different --out-dir)"}
            )
            continue
        # Never let two inputs map to the same output within one run.
        out_key = str(out_path).lower()
        if out_key in seen_outputs:
            results.append(
                {"pdf": pdf.name, "json": json_file.name, "output": None,
                 "status": f"error: output name collides with '{seen_outputs[out_key]}'"}
            )
            continue
        try:
            with PDFMetadataEditor(pdf) as editor:
                if merge:
                    editor.import_json(json_file, replace=False)
                else:
                    editor.apply_json(json_file)
                editor.save(out_path)
            seen_outputs[out_key] = pdf.name
            results.append(
                {"pdf": pdf.name, "json": json_file.name,
                 "output": str(out_path), "status": "ok"}
            )
        except PDFMetadataError as exc:
            results.append(
                {"pdf": pdf.name, "json": json_file.name, "output": None,
                 "status": f"error: {exc}"}
            )
        except Exception as exc:  # never let one bad file stop the whole batch
            results.append(
                {"pdf": pdf.name, "json": json_file.name, "output": None,
                 "status": f"error: {type(exc).__name__}: {exc}"}
            )
    return results
