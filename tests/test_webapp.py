"""Tests for the local web GUI. Skipped automatically if Flask isn't installed."""

import io
import re
import zipfile

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


def _pdf_with_extra_xmp(tmp_path):
    path = tmp_path / "x.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(120, 120))
    pdf.docinfo["/Title"] = "Doc"
    pdf.save(path)
    pdf.close()
    with pikepdf.open(path, allow_overwriting_input=True) as p:
        with p.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as x:
            x["photoshop:Headline"] = "Big News"
        p.save(path)
    return path.read_bytes()


def test_gui_shows_extra_xmp_readonly(client, tmp_path):
    data = _pdf_with_extra_xmp(tmp_path)
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(data), "x.pdf")},
        content_type="multipart/form-data",
    )
    body = resp.data.decode()
    assert "photoshop:Headline" in body  # unmanaged tag surfaced
    assert "read-only" in body


def test_index_shows_upload_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Drag a PDF here" in resp.data


def test_page_has_dark_mode_and_a11y(client):
    html = client.get("/").data.decode()
    assert "prefers-color-scheme: dark" in html  # adapts to system dark mode
    assert "focus-visible" in html  # keyboard focus styles


def test_page_has_favicon_and_quit(client):
    html = client.get("/").data.decode()
    assert 'rel="icon"' in html  # favicon
    assert ">Quit<" in html  # quit button


def test_quit_returns_goodbye(client):
    # In TESTING mode the server isn't actually stopped.
    resp = client.post("/quit")
    assert resp.status_code == 200
    assert b"pdfmeta has stopped" in resp.data


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


def test_editor_shows_page_count_and_size(client):
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(_pdf_bytes()), "f.pdf")},
        content_type="multipart/form-data",
    )
    body = resp.data.decode()
    assert "1 page" in body  # single-page test PDF
    assert "KB" in body or "B)" in body  # file size shown


def test_too_large_upload_friendly_error(client):
    client.application.config["MAX_CONTENT_LENGTH"] = 100  # tiny cap for the test
    big = b"%PDF-1.4\n" + b"0" * 5000
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(big), "big.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413
    assert b"too large" in resp.data


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
    assert b"Drag a PDF here" in resp.data


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


def test_scrub_removes_everything(client, tmp_path):
    token = _open_and_get_token(client, _pdf_bytes())
    resp = client.post("/scrub", data=MultiDict([("token", token), ("filename", "f.pdf")]))
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    out = tmp_path / "clean.pdf"
    out.write_bytes(resp.data)
    with PDFMetadataEditor(out) as ed:
        assert ed.read_all() == {"Document Info": {}, "XMP": {}}


def test_scrub_bad_token(client):
    resp = client.post("/scrub", data={"token": "nope"})
    assert resp.status_code == 400


def test_batch_open_and_apply(client, tmp_path):
    data = MultiDict()
    for name in ("a.pdf", "b.pdf"):
        data.add("pdfs", (io.BytesIO(_pdf_bytes(title="old")), name))
    resp = client.post("/batch-open", data=data, content_type="multipart/form-data")
    body = resp.data.decode()
    assert "Apply to all" in body
    token = re.search(r'name="token" value="([0-9a-f]{32})"', body).group(1)

    resp = client.post(
        "/batch-apply", data=MultiDict([("token", token), ("key", "Title"), ("value", "New")])
    )
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    assert set(zf.namelist()) == {"a.pdf", "b.pdf"}
    for name in zf.namelist():
        out = tmp_path / name
        out.write_bytes(zf.read(name))
        with PDFMetadataEditor(out) as ed:
            assert ed.read_docinfo()["Title"] == "New"


def test_batch_open_no_files(client):
    resp = client.post("/batch-open", data={}, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Please choose one or more PDF files" in resp.data


def test_batch_apply_bad_token(client):
    resp = client.post("/batch-apply", data={"token": "nope"})
    assert resp.status_code == 400


# --------------------------------------------------- local-only security guard


def test_rejects_foreign_host(client):
    # Simulates DNS rebinding: a request addressed to some other hostname.
    resp = client.get("/", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403


def test_rejects_cross_origin_post(client):
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(_pdf_bytes()), "f.pdf")},
        content_type="multipart/form-data",
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_allows_same_origin_post(client):
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(_pdf_bytes()), "f.pdf")},
        content_type="multipart/form-data",
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert resp.status_code == 200


def test_localhost_get_ok(client):
    assert client.get("/", headers={"Host": "localhost:8000"}).status_code == 200


def test_editor_page_has_scrub_button(client):
    token = _open_and_get_token(client, _pdf_bytes())
    # Re-open to get the editor page body containing the button.
    resp = client.post(
        "/open",
        data={"pdf": (io.BytesIO(_pdf_bytes()), "f.pdf")},
        content_type="multipart/form-data",
    )
    assert "Remove all metadata" in resp.data.decode()
    assert token  # token flow works


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
