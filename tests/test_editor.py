"""Tests for pdfmeta. Run with: pytest

The package is imported from ``src/`` via the ``pythonpath`` setting in
pyproject.toml, so no manual path manipulation is needed here.
"""

import json

import pikepdf
import pytest

from pdfmeta.editor import (
    PDFMetadataEditor,
    PDFMetadataError,
    _normalize_key,
    _to_pdf_date,
)
from pdfmeta.batch import process_folder
from pdfmeta.cli import main


@pytest.fixture
def blank_pdf(tmp_path):
    """Create a minimal one-page PDF to edit."""
    path = tmp_path / "blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(path)
    pdf.close()
    return path


def test_normalize_key():
    assert _normalize_key("title") == "/Title"
    assert _normalize_key("TITLE") == "/Title"
    assert _normalize_key("/title") == "/Title"      # leading slash + case
    assert _normalize_key("/TITLE") == "/Title"
    assert _normalize_key("Department") == "/Department"
    assert _normalize_key("/Custom") == "/Custom"
    assert _normalize_key(" Author ") == "/Author"   # surrounding whitespace
    with pytest.raises(PDFMetadataError):
        _normalize_key("   ")
    with pytest.raises(PDFMetadataError):
        _normalize_key("/")


def test_set_and_read_standard(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Quarterly Report")
        ed.set_field("author", "Shivaji")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["Title"] == "Quarterly Report"
    assert data["Author"] == "Shivaji"


def test_custom_field(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("Department", "Finance")
        ed.set_field("ReviewStatus", "Approved")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["Department"] == "Finance"
    assert data["ReviewStatus"] == "Approved"


def test_remove_field(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("Department", "Finance")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.remove_field("Department") is True
        assert ed.remove_field("Nope") is False
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert "Department" not in ed.read()


def test_clear(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_many({"title": "X", "Department": "Y"})
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.clear()
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.read() == {}


def test_json_roundtrip(blank_pdf, tmp_path):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_many({"title": "Doc", "Department": "Finance"})
        ed.save()
    jpath = tmp_path / "meta.json"
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.export_json(jpath)
    loaded = json.loads(jpath.read_text())
    assert loaded["Title"] == "Doc"
    assert loaded["Department"] == "Finance"

    # Import into a fresh copy with replace.
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("Stale", "remove-me")
        ed.import_json(jpath, replace=True)
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert "Stale" not in data
    assert data["Department"] == "Finance"


def test_missing_file():
    with pytest.raises(PDFMetadataError):
        PDFMetadataEditor("/no/such/file.pdf")


def test_cli_view(blank_pdf, capsys):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Report")
        ed.set_field("Department", "Finance")
        ed.save()
    assert main(["view", str(blank_pdf)]) == 0
    out = capsys.readouterr().out
    assert "[Document Info]" in out
    assert "[XMP]" in out
    assert "Report" in out and "Finance" in out


def test_cli_view_json(blank_pdf, capsys):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Report")
        ed.set_field("Department", "Finance")
        ed.save()
    assert main(["view", str(blank_pdf), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["Document Info"]["Title"] == "Report"
    assert data["Document Info"]["Department"] == "Finance"


# --------------------------------------------------------------------- edges

def test_custom_key_with_spaces_and_unicode(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("Review Status", "Approved")
        ed.set_field("title", "Résumé — 报告")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["Review Status"] == "Approved"
    assert data["Title"] == "Résumé — 报告"


def test_pages_preserved_after_in_place_save(tmp_path):
    path = tmp_path / "multi.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page(page_size=(612, 792))
    pdf.save(path)
    pdf.close()
    with PDFMetadataEditor(path) as ed:
        ed.set_field("title", "X")
        ed.save()
    with pikepdf.open(path) as pdf:
        assert len(pdf.pages) == 3


def test_xmp_synced_for_standard_fields(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Report")
        ed.set_field("author", "Shivaji")
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        xmp = pdf.open_metadata()
        assert xmp.get("dc:title") == "Report"
        assert xmp.get("dc:creator") == ["Shivaji"]


def test_update_replaces_xmp_value(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("author", "First")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("author", "Second")
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        assert pdf.open_metadata().get("dc:creator") == ["Second"]


def test_remove_clears_xmp(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("author", "Shivaji")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.remove_field("author")
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        assert "dc:creator" not in pdf.open_metadata()


def test_clear_removes_metadata_stream(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "X")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.clear()
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        assert "/Metadata" not in pdf.Root
        assert len(pdf.docinfo) == 0


def test_import_coerces_non_strings(blank_pdf, tmp_path):
    jpath = tmp_path / "m.json"
    jpath.write_text(json.dumps({"Title": "T", "Year": 2026, "Reviewed": True}))
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.import_json(jpath)
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["Year"] == "2026"
    assert data["Reviewed"] == "True"


def test_import_rejects_non_object(blank_pdf, tmp_path):
    jpath = tmp_path / "bad.json"
    jpath.write_text(json.dumps(["not", "an", "object"]))
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError):
            ed.import_json(jpath)


def test_not_a_file(tmp_path):
    with pytest.raises(PDFMetadataError):
        PDFMetadataEditor(tmp_path)  # a directory


def test_password_protected(tmp_path):
    path = tmp_path / "enc.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(path, encryption=pikepdf.Encryption(owner="o", user="u"))
    pdf.close()
    with pytest.raises(PDFMetadataError, match="password"):
        PDFMetadataEditor(path)


def test_get_field(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Report")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.get_field("title") == "Report"
        assert ed.get_field("author") is None


def test_output_flag_leaves_original_untouched(blank_pdf, tmp_path):
    out = tmp_path / "copy.pdf"
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "Copy")
        ed.save(out)
    with PDFMetadataEditor(blank_pdf) as ed:
        assert "Title" not in ed.read()      # original unchanged
    with PDFMetadataEditor(out) as ed:
        assert ed.read()["Title"] == "Copy"   # new file has it


# ----------------------------------------------------------------------- CLI

def test_cli_missing_file():
    assert main(["view", "/no/such/file.pdf"]) == 1


# ------------------------------------------------------------------- dates

def test_to_pdf_date_formats():
    # Date-only -> midnight, PDF format with an offset.
    assert _to_pdf_date("2026-01-15").startswith("D:20260115000000")
    # Date + time.
    assert _to_pdf_date("2026-01-15 14:30").startswith("D:20260115143000")
    # Already a PDF date -> passed through untouched.
    assert _to_pdf_date("D:20260101000000Z") == "D:20260101000000Z"
    # Trailing apostrophe present when there is a UTC offset.
    out = _to_pdf_date("2026-01-15 14:30:00+05:30")
    assert out == "D:20260115143000+05'30'"


def test_to_pdf_date_rejects_garbage():
    with pytest.raises(PDFMetadataError):
        _to_pdf_date("not a date")


def test_date_aliases_normalize():
    assert _normalize_key("created") == "/CreationDate"
    assert _normalize_key("modified") == "/ModDate"
    assert _normalize_key("CreationDate") == "/CreationDate"
    assert _normalize_key("moddate") == "/ModDate"


def test_set_creation_and_mod_date(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("created", "2026-01-15")
        ed.set_field("modified", "2026-02-20 09:45")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["CreationDate"].startswith("D:20260115000000")
    assert data["ModDate"].startswith("D:20260220094500")


def test_date_synced_to_xmp(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("created", "2026-01-15 14:30:00+05:30")
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        assert pdf.open_metadata().get("xmp:CreateDate") == "2026-01-15T14:30:00+05:30"


def test_apply_json_with_friendly_date(blank_pdf, tmp_path):
    jpath = tmp_path / "m.json"
    jpath.write_text(json.dumps({"Title": "T", "CreationDate": "2026-01-15"}))
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.apply_json(jpath)
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["CreationDate"].startswith("D:20260115000000")


# --------------------------------------------------------------- XMP fields

def test_set_and_read_all_xmp_fields(blank_pdf):
    values = {
        "copyright": "© 2026 Shivaji",
        "rights-marked": "yes",
        "license": "https://example.com/license",
        "usage-terms": "CC BY 4.0",
        "owner": "Shivaji Chaprana",
        "language": "en, hi",
        "publisher": "Acme Press",
        "contributor": "Aruna Sirohi",
        "rating": "5",
        "label": "Final",
        "metadata-date": "2026-01-15",
        "document-id": "uuid:doc-123",
        "instance-id": "uuid:inst-456",
        "pdfa-part": "3",
        "pdfa-conformance": "B",
    }
    with PDFMetadataEditor(blank_pdf) as ed:
        for name, val in values.items():
            ed.set_field(name, val)
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["copyright"] == "© 2026 Shivaji"
    assert data["rights-marked"] == "True"          # yes -> True
    assert data["license"] == "https://example.com/license"
    assert data["owner"] == "Shivaji Chaprana"
    assert data["language"] == "en, hi"              # array round-trips
    assert data["rating"] == "5"
    assert data["metadata-date"].startswith("2026-01-15T")
    assert data["document-id"] == "uuid:doc-123"
    assert data["pdfa-conformance"] == "B"


def test_xmp_field_does_not_touch_docinfo(tmp_path):
    path = tmp_path / "pre.pdf"
    _pdf_with_docinfo_only(path)  # has Title + Author
    with PDFMetadataEditor(path) as ed:
        ed.set_field("copyright", "© 2026")
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data["Title"] == "Original Title"
    assert data["Author"] == "Original Author"
    assert data["copyright"] == "© 2026"


def test_xmp_aliases(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("rights", "© alias")     # alias for copyright
        ed.set_field("lang", "fr")            # alias for language
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        data = ed.read()
    assert data["copyright"] == "© alias"
    assert data["language"] == "fr"


def test_remove_xmp_field(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("copyright", "© 2026")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.remove_field("copyright") is True
        assert ed.remove_field("copyright") is False
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert "copyright" not in ed.read()


def test_rights_marked_no(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("rights-marked", "no")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.read()["rights-marked"] == "False"


def test_rights_marked_invalid(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError):
            ed.set_field("rights-marked", "maybe")


# --------------------------------------------------------------- Trapped

def test_trapped_values(blank_pdf):
    for given, expected in [("true", "/True"), ("False", "/False"),
                            ("unknown", "/Unknown"), ("/True", "/True")]:
        with PDFMetadataEditor(blank_pdf) as ed:
            ed.set_field("trapped", given)
            ed.save()
        with PDFMetadataEditor(blank_pdf) as ed:
            assert ed.read()["Trapped"] == expected


def test_trapped_invalid(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError):
            ed.set_field("trapped", "sometimes")


def test_apply_replaces_including_xmp(tmp_path):
    path = tmp_path / "pre.pdf"
    _pdf_with_docinfo_only(path)
    with PDFMetadataEditor(path) as ed:
        ed.set_field("copyright", "old")
        ed.save()
    jpath = tmp_path / "m.json"
    jpath.write_text(json.dumps({"Title": "Only", "language": "en"}))
    with PDFMetadataEditor(path) as ed:
        ed.apply_json(jpath)
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data == {"Title": "Only", "language": "en"}


def test_capitalized_name_is_custom_docinfo_not_xmp(tmp_path):
    # Regression: a docinfo custom field like /Owner must NOT be shadowed by
    # the lowercase XMP `owner` field. Capitalized -> docinfo; lowercase -> XMP.
    path = tmp_path / "o.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.docinfo["/Title"] = "Report"
    pdf.docinfo["/Owner"] = "Legal Dept"
    pdf.save(path)
    pdf.close()
    with PDFMetadataEditor(path) as ed:
        assert ed.get_field("Owner") == "Legal Dept"     # reachable as docinfo
        assert ed.read()["Owner"] == "Legal Dept"

    # export -> apply must preserve /Owner exactly (no relocation/rename).
    jpath = tmp_path / "m.json"
    with PDFMetadataEditor(path) as ed:
        ed.export_json(jpath)
    with PDFMetadataEditor(path) as ed:
        ed.apply_json(jpath)
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data["Owner"] == "Legal Dept"
    assert "owner" not in data          # not moved into XMP
    assert data["Title"] == "Report"


def test_lowercase_owner_still_goes_to_xmp(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("owner", "Shivaji")   # lowercase -> XMP xmpRights:Owner
        ed.save()
    with pikepdf.open(blank_pdf) as pdf:
        assert pdf.open_metadata().get("xmpRights:Owner") == ["Shivaji"]


def test_metadata_date_accepts_pdf_date(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("metadata-date", "D:20260101000000Z")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.read()["metadata-date"].startswith("2026-01-01T")


# --------------------------------------------------------- batch folder run

def _make_pdf(path, title=None):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    if title:
        pdf.docinfo["/Title"] = title
    pdf.save(path)
    pdf.close()


def _dirs(tmp_path):
    pdf_dir = tmp_path / "in_pdf"
    json_dir = tmp_path / "in_json"
    out_dir = tmp_path / "out"
    pdf_dir.mkdir()
    json_dir.mkdir()
    return pdf_dir, json_dir, out_dir


def test_batch_single_json_applies_to_all(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf", "Old A")
    _make_pdf(pdf_dir / "b.pdf", "Old B")
    (json_dir / "meta.json").write_text(json.dumps({"Title": "T", "Author": "X"}))

    results = process_folder(pdf_dir, json_dir, out_dir)
    assert all(r["status"] == "ok" for r in results)
    assert len(results) == 2
    for name in ("a.pdf", "b.pdf"):
        assert (out_dir / name).exists()
        with PDFMetadataEditor(out_dir / name) as ed:
            data = ed.read()
        assert data == {"Title": "T", "Author": "X"}
    # originals untouched
    with PDFMetadataEditor(pdf_dir / "a.pdf") as ed:
        assert ed.read()["Title"] == "Old A"


def test_batch_same_name_json_preferred(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "report.pdf")
    _make_pdf(pdf_dir / "scan.pdf")
    (json_dir / "report.json").write_text(json.dumps({"Title": "Report Meta"}))
    (json_dir / "scan.json").write_text(json.dumps({"Title": "Scan Meta"}))

    process_folder(pdf_dir, json_dir, out_dir)
    with PDFMetadataEditor(out_dir / "report.pdf") as ed:
        assert ed.read()["Title"] == "Report Meta"
    with PDFMetadataEditor(out_dir / "scan.pdf") as ed:
        assert ed.read()["Title"] == "Scan Meta"


def test_batch_skips_when_no_matching_json(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf")
    _make_pdf(pdf_dir / "b.pdf")
    # two JSONs, neither matching by name -> ambiguous -> skip
    (json_dir / "x.json").write_text(json.dumps({"Title": "X"}))
    (json_dir / "y.json").write_text(json.dumps({"Title": "Y"}))

    results = process_folder(pdf_dir, json_dir, out_dir)
    assert all(r["status"].startswith("skipped") for r in results)
    assert not (out_dir / "a.pdf").exists()


def test_batch_merge_keeps_existing(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf", "Keep Me")
    (json_dir / "meta.json").write_text(json.dumps({"Author": "Added"}))

    process_folder(pdf_dir, json_dir, out_dir, merge=True)
    with PDFMetadataEditor(out_dir / "a.pdf") as ed:
        data = ed.read()
    assert data["Title"] == "Keep Me"     # kept
    assert data["Author"] == "Added"      # added


def test_batch_missing_dir_raises(tmp_path):
    with pytest.raises(PDFMetadataError):
        process_folder(tmp_path / "nope", tmp_path, tmp_path / "out")


def test_batch_no_json_raises_clear_error(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf")
    # json_dir exists but is empty
    with pytest.raises(PDFMetadataError, match="No .json"):
        process_folder(pdf_dir, json_dir, out_dir)


def test_batch_no_pdfs_returns_empty(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    (json_dir / "meta.json").write_text(json.dumps({"Title": "T"}))
    assert process_folder(pdf_dir, json_dir, out_dir) == []


def test_batch_malformed_json_reported_not_crash(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf")
    (json_dir / "meta.json").write_text("{ this is not valid json ")
    results = process_folder(pdf_dir, json_dir, out_dir)
    assert len(results) == 1
    assert results[0]["status"].startswith("error")
    assert not (out_dir / "a.pdf").exists()


def test_batch_bad_pdf_does_not_stop_good_ones(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "good.pdf")
    (pdf_dir / "bad.pdf").write_text("not a real pdf")   # corrupt
    (json_dir / "meta.json").write_text(json.dumps({"Title": "T"}))
    results = process_folder(pdf_dir, json_dir, out_dir)
    by_name = {r["pdf"]: r["status"] for r in results}
    assert by_name["good.pdf"] == "ok"
    assert by_name["bad.pdf"].startswith("error")
    assert (out_dir / "good.pdf").exists()       # good one still produced
    assert not (out_dir / "bad.pdf").exists()


def test_import_json_missing_file_raises(blank_pdf, tmp_path):
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError, match="not found"):
            ed.import_json(tmp_path / "nope.json")


def test_import_json_invalid_json_raises(blank_pdf, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid ")
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError, match="not valid JSON"):
            ed.import_json(bad)


def test_import_json_rejects_nested_values(blank_pdf, tmp_path):
    bad = tmp_path / "n.json"
    bad.write_text(json.dumps({"Title": {"nested": 1}}))
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError, match="must be text"):
            ed.import_json(bad)
    bad.write_text(json.dumps({"Tags": [1, 2, 3]}))
    with PDFMetadataEditor(blank_pdf) as ed:
        with pytest.raises(PDFMetadataError, match="must be text"):
            ed.import_json(bad)


def test_batch_refuses_to_overwrite_original(tmp_path):
    # out_dir == pdf_dir must NOT clobber the input.
    pdf_dir = tmp_path / "same"
    json_dir = tmp_path / "j"
    pdf_dir.mkdir()
    json_dir.mkdir()
    _make_pdf(pdf_dir / "doc.pdf", "PRECIOUS")
    (json_dir / "m.json").write_text(json.dumps({"Title": "NEW"}))

    results = process_folder(pdf_dir, json_dir, pdf_dir)  # out == in
    assert results[0]["status"].startswith("error")
    with PDFMetadataEditor(pdf_dir / "doc.pdf") as ed:
        assert ed.read()["Title"] == "PRECIOUS"          # untouched


def test_batch_uppercase_pdf_extension(tmp_path):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "REPORT.PDF", "Up")
    (json_dir / "m.json").write_text(json.dumps({"Title": "T"}))
    results = process_folder(pdf_dir, json_dir, out_dir)
    assert results and results[0]["status"] == "ok"
    assert (out_dir / "REPORT.PDF").exists()


def test_cli_run_nonzero_exit_on_failure(tmp_path, capsys):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    (pdf_dir / "broken.pdf").write_text("not a pdf")
    (json_dir / "m.json").write_text(json.dumps({"Title": "T"}))
    rc = main(["run", "--pdf-dir", str(pdf_dir),
               "--json-dir", str(json_dir), "--out-dir", str(out_dir)])
    assert rc == 1
    assert "Done: 0 of 1" in capsys.readouterr().out


def test_cli_view_empty_json(blank_pdf, capsys):
    assert main(["view", str(blank_pdf), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"Document Info": {}, "XMP": {}}


def test_view_survives_malformed_xmp(tmp_path):
    path = tmp_path / "x.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    # Inject a broken XMP stream directly.
    pdf.Root.Metadata = pdf.make_stream(b"<x>not valid xmp<", Type=pikepdf.Name.Metadata)
    pdf.save(path)
    pdf.close()
    with PDFMetadataEditor(path) as ed:
        result = ed.read_all()               # must not raise
    assert "Document Info" in result and "XMP" in result


# ---------------------------------------------- complete reader (view --all)

def test_read_all_surfaces_unknown_xmp_tags(blank_pdf):
    # Write XMP tags that are NOT in pdfmeta's registry, directly via pikepdf,
    # then confirm read_all/read_xmp surface them (no assumptions).
    with pikepdf.open(blank_pdf, allow_overwriting_input=True) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as x:
            x["dc:title"] = "T"
            x["xmp:Nickname"] = "Nick"            # not in registry
            x["photoshop:Headline"] = "Big News"  # not in registry
        pdf.docinfo["/Title"] = "T"
        pdf.docinfo["/CustomThing"] = "hello"
        pdf.save(blank_pdf)

    with PDFMetadataEditor(blank_pdf) as ed:
        allmeta = ed.read_all()
    docinfo = allmeta["Document Info"]
    xmp = allmeta["XMP"]
    assert docinfo["Title"] == "T"
    assert docinfo["CustomThing"] == "hello"
    assert xmp["dc:title"] == "T"
    assert xmp["xmp:Nickname"] == "Nick"          # surfaced despite unknown
    assert xmp["photoshop:Headline"] == "Big News"


def test_read_xmp_empty_when_no_packet(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        assert ed.read_xmp() == {}
        assert ed.xmp_packet() is None


def test_xmp_packet_returns_xml(blank_pdf):
    with PDFMetadataEditor(blank_pdf) as ed:
        ed.set_field("title", "T")
        ed.save()
    with PDFMetadataEditor(blank_pdf) as ed:
        packet = ed.xmp_packet()
    assert packet is not None
    assert "<x:xmpmeta" in packet or "<?xpacket" in packet


def test_replace_docinfo(tmp_path):
    path = tmp_path / "r.pdf"
    _pdf_with_docinfo_only(path)  # Title + Author
    with PDFMetadataEditor(path) as ed:
        ed.set_field("copyright", "© keep")   # an XMP-only tag
        ed.replace_docinfo({"Title": "Only Title", "Department": "Finance"})
        ed.save()
    with PDFMetadataEditor(path) as ed:
        docinfo = ed.read_docinfo()
        allmeta = ed.read_all()
    assert docinfo == {"Title": "Only Title", "Department": "Finance"}
    assert "Author" not in docinfo                     # dropped row removed
    assert allmeta["XMP"].get("dc:rights") == "© keep"  # XMP-only tag preserved


def test_cli_run_merge(tmp_path, capsys):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf", "Keep Me")
    (json_dir / "m.json").write_text(json.dumps({"Author": "Added"}))
    rc = main(["run", "--merge", "--pdf-dir", str(pdf_dir),
               "--json-dir", str(json_dir), "--out-dir", str(out_dir)])
    assert rc == 0
    with PDFMetadataEditor(out_dir / "a.pdf") as ed:
        data = ed.read_docinfo()
    assert data["Title"] == "Keep Me"      # kept by --merge
    assert data["Author"] == "Added"


def test_cli_run(tmp_path, capsys):
    pdf_dir, json_dir, out_dir = _dirs(tmp_path)
    _make_pdf(pdf_dir / "a.pdf")
    (json_dir / "meta.json").write_text(json.dumps({"Title": "T"}))
    rc = main([
        "run",
        "--pdf-dir", str(pdf_dir),
        "--json-dir", str(json_dir),
        "--out-dir", str(out_dir),
    ])
    assert rc == 0
    assert (out_dir / "a.pdf").exists()
    assert "Done: 1 of 1" in capsys.readouterr().out


# ------------------------------------------------- regression: XMP data loss

def _pdf_with_docinfo_only(path):
    """A PDF that has docinfo metadata but NO XMP stream — like most real
    PDFs produced by Word, LaTeX, Acrobat, etc."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.docinfo["/Title"] = "Original Title"
    pdf.docinfo["/Author"] = "Original Author"
    pdf.save(path)
    pdf.close()


def test_editing_one_field_preserves_preexisting_docinfo(tmp_path):
    # Regression: editing a single standard field must NOT wipe the other
    # docinfo fields that already existed in the file.
    path = tmp_path / "pre.pdf"
    _pdf_with_docinfo_only(path)
    with PDFMetadataEditor(path) as ed:
        ed.set_field("subject", "New Subject")
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data["Title"] == "Original Title"
    assert data["Author"] == "Original Author"
    assert data["Subject"] == "New Subject"


def test_editing_custom_field_preserves_preexisting_docinfo(tmp_path):
    path = tmp_path / "pre.pdf"
    _pdf_with_docinfo_only(path)
    with PDFMetadataEditor(path) as ed:
        ed.set_field("Department", "Finance")
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data["Title"] == "Original Title"
    assert data["Author"] == "Original Author"
    assert data["Department"] == "Finance"


def test_apply_json_replaces_everything(tmp_path):
    # apply must leave the PDF with EXACTLY the JSON fields — no leftovers.
    path = tmp_path / "pre.pdf"
    _pdf_with_docinfo_only(path)  # starts with Title + Author
    jpath = tmp_path / "meta.json"
    jpath.write_text(json.dumps({"Title": "Only This", "Department": "Finance"}))
    with PDFMetadataEditor(path) as ed:
        ed.apply_json(jpath)
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data == {"Title": "Only This", "Department": "Finance"}
    assert "Author" not in data  # original extra field removed


def test_empty_value_is_preserved(tmp_path):
    # An explicitly-set empty string should persist as an empty field,
    # not silently vanish.
    path = tmp_path / "e.pdf"
    _pdf_with_docinfo_only(path)
    with PDFMetadataEditor(path) as ed:
        ed.set_field("subject", "")
        ed.save()
    with PDFMetadataEditor(path) as ed:
        data = ed.read()
    assert data.get("Subject") == ""
    assert data["Title"] == "Original Title"
