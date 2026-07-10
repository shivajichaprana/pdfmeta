"""CLI-level tests for the gui dispatch and run edge branches."""

import json
import sys
import types

import pikepdf
import pytest

from pdfmeta.cli import _run_gui, main


class _FakeApp:
    def run(self, **kwargs):
        self.ran = True


def test_run_gui_success(monkeypatch):
    import pdfmeta.webapp as wa

    monkeypatch.setattr(wa, "create_app", lambda: _FakeApp())
    assert _run_gui(8123, open_browser=False) == 0


def test_run_gui_missing_flask(monkeypatch, capsys):
    # Simulate Flask not being installed: a webapp module without create_app
    # makes `from .webapp import create_app` raise ImportError.
    dummy = types.ModuleType("pdfmeta.webapp")
    monkeypatch.setitem(sys.modules, "pdfmeta.webapp", dummy)
    assert _run_gui(8123, open_browser=False) == 1
    assert "Flask" in capsys.readouterr().err


def test_cli_gui_dispatch(monkeypatch):
    import pdfmeta.webapp as wa

    monkeypatch.setattr(wa, "create_app", lambda: _FakeApp())
    assert main(["gui", "--no-browser", "--port", "8124"]) == 0


def test_cli_run_no_pdfs(tmp_path, capsys):
    pdf_dir = tmp_path / "p"
    json_dir = tmp_path / "j"
    pdf_dir.mkdir()
    json_dir.mkdir()
    (json_dir / "m.json").write_text(json.dumps({"Title": "T"}))
    rc = main(
        [
            "run",
            "--pdf-dir",
            str(pdf_dir),
            "--json-dir",
            str(json_dir),
            "--out-dir",
            str(tmp_path / "o"),
        ]
    )
    assert rc == 0
    assert "No PDF files found" in capsys.readouterr().out


def _pdf_with_metadata(path):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.docinfo["/Title"] = "Secret Title"
    pdf.docinfo["/Author"] = "Secret Author"
    pdf.save(path)
    pdf.close()


def test_cli_scrub_in_place(tmp_path, capsys):
    from pdfmeta.editor import PDFMetadataEditor

    path = tmp_path / "doc.pdf"
    _pdf_with_metadata(path)
    assert main(["scrub", str(path)]) == 0
    assert "Removed all metadata" in capsys.readouterr().out
    with PDFMetadataEditor(path) as ed:
        assert ed.read_all() == {"Document Info": {}, "XMP": {}}


def test_cli_scrub_output_keeps_original(tmp_path):
    from pdfmeta.editor import PDFMetadataEditor

    path = tmp_path / "doc.pdf"
    out = tmp_path / "clean.pdf"
    _pdf_with_metadata(path)
    assert main(["scrub", str(path), "-o", str(out)]) == 0
    with PDFMetadataEditor(out) as ed:
        assert ed.read_docinfo() == {}
    with PDFMetadataEditor(path) as ed:
        assert ed.read_docinfo()["Title"] == "Secret Title"  # original untouched


def test_cli_template_to_stdout(tmp_path, capsys):
    path = tmp_path / "doc.pdf"
    _pdf_with_metadata(path)
    assert main(["template", str(path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["Title"] == "Secret Title"
    assert data["Author"] == "Secret Author"


def test_cli_template_to_file(tmp_path):
    path = tmp_path / "doc.pdf"
    out = tmp_path / "meta.json"
    _pdf_with_metadata(path)
    assert main(["template", str(path), "-o", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["Title"] == "Secret Title"


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "pdfmeta" in capsys.readouterr().out
