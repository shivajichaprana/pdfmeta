"""Tests for the local web GUI. Skipped automatically if Flask isn't installed."""

import io
import re

import pikepdf
import pytest

flask = pytest.importorskip("flask")
from werkzeug.datastructures import MultiDict

from pdfmeta.editor import PDFMetadataEditor
from pdfmeta.webapp import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _pdf_bytes(title="Original Title", author="Original Author"):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    if title:
        pdf.docinfo["/Title"] = title
    if author:
        pdf.docinfo["/Author"] = author
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _pdf_with_copyright(tmp_path):
    path = tmp_path / "c.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.docinfo["/Title"] = "Doc"
    pdf.save(path)
    pdf.close()
    with PDFMetadataEditor(path) as ed:
        ed.set_field("copyright", "© Original")
        ed.save()
    return path.read_bytes()


def test_index_shows_upload_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Choose a PDF" in resp.data


def test_gui_shows_and_edits_xmp_field(client, tmp_path):
    data = _pdf_with_copyright(tmp_path)
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(data), "c.pdf")},
        content_type="multipart/form-data",
    )
    body = resp.data.decode()
    assert "copyright" in body and "© Original" in body  # XMP tag is shown
    token = re.search(r'name="token" value="([0-9a-f]{32})"', body).group(1)

    resp = client.post(
        "/save",
        data=MultiDict(
            [
                ("token", token),
                ("filename", "c.pdf"),
                ("key", "Title"),
                ("value", "Doc"),
                ("key", "copyright"),
                ("value", "© Updated"),
            ]
        ),
    )
    out = tmp_path / "out.pdf"
    out.write_bytes(resp.data)
    with PDFMetadataEditor(out) as ed:
        assert ed.read()["copyright"] == "© Updated"  # XMP edit persisted


def test_open_shows_current_tags(client):
    data = {"pdf": (io.BytesIO(_pdf_bytes()), "report.pdf")}
    resp = client.post("/open", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Original Title" in body
    assert "Original Author" in body
    assert 'name="token"' in body


def test_open_rejects_non_pdf(client):
    data = {"pdf": (io.BytesIO(b"not a pdf"), "bad.pdf")}
    resp = client.post("/open", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    # falls back to the upload page with an error, not a crash
    assert b"Choose a PDF" in resp.data


def _open_and_get_token(client, pdf_bytes):
    resp = client.post(
        "/open", data={"pdf": (io.BytesIO(pdf_bytes), "f.pdf")}, content_type="multipart/form-data"
    )
    m = re.search(r'name="token" value="([0-9a-f]{32})"', resp.data.decode())
    assert m, "token not found in editor page"
    return m.group(1)


def test_save_applies_edits_and_downloads(client, tmp_path):
    token = _open_and_get_token(client, _pdf_bytes())
    # Edit Title, drop Author (omit it), add a new custom tag.
    resp = client.post(
        "/save",
        data=MultiDict(
            [
                ("token", token),
                ("filename", "f.pdf"),
                ("key", "Title"),
                ("value", "New Title"),
                ("key", "Department"),
                ("value", "Finance"),
            ]
        ),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    out = tmp_path / "out.pdf"
    out.write_bytes(resp.data)
    with PDFMetadataEditor(out) as ed:
        data = ed.read_docinfo()
    assert data["Title"] == "New Title"
    assert data["Department"] == "Finance"
    assert "Author" not in data  # deleted (omitted) tag is gone


def test_save_with_bad_token(client):
    resp = client.post("/save", data={"token": "notavalidtoken", "key": "Title", "value": "X"})
    # invalid token -> 400 from _token_path guard
    assert resp.status_code == 400


def test_save_cleans_up_temp_file(client, monkeypatch, tmp_path):
    import pdfmeta.webapp as wa

    monkeypatch.setattr(wa, "_UPLOAD_DIR", tmp_path / "up")
    token = _open_and_get_token(client, _pdf_bytes())
    assert list((tmp_path / "up").glob("*.pdf"))  # temp exists after open
    resp = client.post(
        "/save",
        data=MultiDict([("token", token), ("filename", "f.pdf"), ("key", "Title"), ("value", "X")]),
    )
    assert resp.status_code == 200
    # after the download is served, the temp file is gone
    assert list((tmp_path / "up").glob("*.pdf")) == []


def test_save_handles_nasty_filename(client):
    # A filename with a newline must not crash the save (no 500).
    token = _open_and_get_token(client, _pdf_bytes())
    resp = client.post(
        "/save",
        data=MultiDict(
            [("token", token), ("filename", "bad\r\nname.pdf"), ("key", "Title"), ("value", "X")]
        ),
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"


def test_open_sweeps_stale_uploads(client, monkeypatch, tmp_path):
    import os
    import time

    import pdfmeta.webapp as wa

    updir = tmp_path / "up"
    updir.mkdir()
    monkeypatch.setattr(wa, "_UPLOAD_DIR", updir)
    monkeypatch.setattr(wa, "_STALE_SECONDS", 1)
    stale = updir / ("a" * 32 + ".pdf")
    stale.write_bytes(b"old")
    old = time.time() - 10
    os.utime(stale, (old, old))
    _open_and_get_token(client, _pdf_bytes())  # triggers the sweep
    assert not stale.exists()
