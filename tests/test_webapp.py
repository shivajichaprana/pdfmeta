"""Tests for the local web GUI. Skipped automatically if Flask isn't installed."""

import io
import re

import pikepdf
import pytest

flask = pytest.importorskip("flask")
from werkzeug.datastructures import MultiDict

from pdfmeta.webapp import create_app
from pdfmeta.editor import PDFMetadataEditor


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


def test_index_shows_upload_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Choose a PDF" in resp.data


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
    resp = client.post("/open", data={"pdf": (io.BytesIO(pdf_bytes), "f.pdf")},
                       content_type="multipart/form-data")
    m = re.search(r'name="token" value="([0-9a-f]{32})"', resp.data.decode())
    assert m, "token not found in editor page"
    return m.group(1)


def test_save_applies_edits_and_downloads(client, tmp_path):
    token = _open_and_get_token(client, _pdf_bytes())
    # Edit Title, drop Author (omit it), add a new custom tag.
    resp = client.post("/save", data=MultiDict([
        ("token", token),
        ("filename", "f.pdf"),
        ("key", "Title"), ("value", "New Title"),
        ("key", "Department"), ("value", "Finance"),
    ]))
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    out = tmp_path / "out.pdf"
    out.write_bytes(resp.data)
    with PDFMetadataEditor(out) as ed:
        data = ed.read_docinfo()
    assert data["Title"] == "New Title"
    assert data["Department"] == "Finance"
    assert "Author" not in data          # deleted (omitted) tag is gone


def test_save_with_bad_token(client):
    resp = client.post("/save", data={"token": "notavalidtoken",
                                      "key": "Title", "value": "X"})
    # invalid token -> 400 from _token_path guard
    assert resp.status_code == 400
