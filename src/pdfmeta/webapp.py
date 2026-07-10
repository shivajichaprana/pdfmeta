"""A small local web GUI for viewing and editing PDF metadata.

Runs entirely on your own machine — the PDF never leaves your computer. Upload
a PDF, edit its metadata tags (add / change / delete), click Modify, and
download the result. It reuses :class:`pdfmeta.editor.PDFMetadataEditor`, so the
edits behave exactly like the command-line tool.

Flask is an optional dependency; install it with ``pip install "pdfmeta[gui]"``.
"""

from __future__ import annotations

import re
import secrets
import tempfile
import time
from pathlib import Path

from flask import (
    Flask,
    abort,
    after_this_request,
    render_template_string,
    request,
    send_file,
)

from .editor import PDFMetadataEditor, PDFMetadataError

# Uploaded PDFs are stored here between the upload and the save/download step.
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdfmeta_gui"
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
_STALE_SECONDS = 3600  # remove abandoned uploads older than an hour


def _token_path(token: str) -> Path:
    """Return the temp path for a token, refusing anything that isn't a token."""
    if not _TOKEN_RE.match(token or ""):
        abort(400, "Invalid document token.")
    return _UPLOAD_DIR / f"{token}.pdf"


def _sweep_stale() -> None:
    """Delete abandoned upload temp files so they don't accumulate forever."""
    try:
        cutoff = time.time() - _STALE_SECONDS
        for f in _UPLOAD_DIR.glob("*.pdf"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def _safe_download_name(raw: str) -> str:
    """Turn a user-supplied filename into a safe PDF download name."""
    name = re.sub(r"[\r\n\t]", "", Path(raw or "").name).strip() or "edited.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pdfmeta — PDF metadata editor</title>
<style>
  :root { --line:#e2e4e8; --brand:#2b6cb0; --bg:#f7f8fa; --danger:#c0392b; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: var(--bg); color: #1a1f27; }
  header { background: #fff; border-bottom: 1px solid var(--line); padding: 18px 24px; }
  header h1 { margin: 0; font-size: 20px; }
  header p { margin: 4px 0 0; color: #6b7280; font-size: 13px; }
  main { max-width: 820px; margin: 28px auto; padding: 0 20px; }
  .card { background: #fff; border: 1px solid var(--line); border-radius: 10px;
          padding: 22px; margin-bottom: 20px; }
  .drop { text-align: center; padding: 30px; border: 2px dashed var(--line);
          border-radius: 10px; }
  input[type=text] { width: 100%; padding: 8px 10px; border: 1px solid var(--line);
                     border-radius: 6px; font-size: 14px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 12px; text-transform: uppercase;
       letter-spacing: .04em; color: #6b7280; padding: 6px 8px; }
  td { padding: 5px 8px; vertical-align: middle; }
  td.k { width: 34%; } td.x { width: 42px; text-align: center; }
  .btn { border: 0; border-radius: 7px; padding: 10px 16px; font-size: 14px;
         cursor: pointer; }
  .btn.primary { background: var(--brand); color: #fff; }
  .btn.ghost { background: #eef1f5; color: #1a1f27; }
  .btn.del { background: transparent; color: var(--danger); font-size: 18px;
             line-height: 1; padding: 4px 8px; }
  .row-actions { display: flex; gap: 10px; margin-top: 16px; align-items: center; }
  .flash { background: #fdecea; color: var(--danger); border: 1px solid #f5c6cb;
           padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; }
  .muted { color: #6b7280; font-size: 13px; }
  code { background: #eef1f5; padding: 1px 5px; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <h1>pdfmeta</h1>
  <p>Edit PDF metadata locally — your file never leaves this computer.</p>
</header>
<main>
  {% if error %}<div class="flash">{{ error }}</div>{% endif %}

  {% if not token %}
  <div class="card">
    <form class="drop" method="post" action="{{ url_for('open_pdf') }}"
          enctype="multipart/form-data">
      <p><strong>Choose a PDF to edit</strong></p>
      <p><input type="file" name="pdf" accept="application/pdf,.pdf" required></p>
      <p><button class="btn primary" type="submit">Open</button></p>
      <p class="muted">Nothing is uploaded to the internet. Files are processed
        on your machine only.</p>
    </form>
  </div>
  {% else %}
  <div class="card">
    <p class="muted">Editing <strong>{{ filename }}</strong> — these are the
      document's metadata tags. Change a value, delete a row, or add a new tag,
      then click <strong>Modify &amp; download</strong>.</p>
    <form method="post" action="{{ url_for('save_pdf') }}">
      <input type="hidden" name="token" value="{{ token }}">
      <input type="hidden" name="filename" value="{{ filename }}">
      <table>
        <thead><tr><th>Tag</th><th>Value</th><th></th></tr></thead>
        <tbody id="rows">
          {% for k, v in tags %}
          <tr>
            <td class="k"><input type="text" name="key" value="{{ k }}"></td>
            <td><input type="text" name="value" value="{{ v }}"></td>
            <td class="x"><button type="button" class="btn del"
                onclick="this.closest('tr').remove()" title="Delete tag">&times;</button></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <div class="row-actions">
        <button type="button" class="btn ghost" onclick="addRow()">+ Add tag</button>
        <button type="submit" class="btn primary">Modify &amp; download</button>
        <a class="muted" href="{{ url_for('index') }}">Start over</a>
      </div>
    </form>
  </div>
  <p class="muted">The standard tags are also written to the PDF's XMP stream so
    every viewer stays consistent. Your original file is untouched — this
    downloads a new edited copy.</p>
  {% endif %}
</main>
<script>
  function addRow() {
    var tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="k"><input type="text" name="key" placeholder="e.g. Title"></td>' +
      '<td><input type="text" name="value" placeholder="value"></td>' +
      '<td class="x"><button type="button" class="btn del" ' +
      'onclick="this.closest(\\'tr\\').remove()" title="Delete tag">&times;</button></td>';
    document.getElementById('rows').appendChild(tr);
  }
</script>
</body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = _MAX_UPLOAD_BYTES

    @app.get("/")
    def index() -> str:
        return render_template_string(_PAGE, token=None)

    @app.post("/open")
    def open_pdf():
        uploaded = request.files.get("pdf")
        if uploaded is None or not uploaded.filename:
            return render_template_string(_PAGE, token=None,
                                          error="Please choose a PDF file.")
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _sweep_stale()  # clear out any abandoned uploads
        token = secrets.token_hex(16)
        path = _UPLOAD_DIR / f"{token}.pdf"
        uploaded.save(path)
        try:
            with PDFMetadataEditor(path) as editor:
                tags = list(editor.read_docinfo().items())
        except PDFMetadataError as exc:
            path.unlink(missing_ok=True)
            return render_template_string(_PAGE, token=None, error=str(exc))
        return render_template_string(
            _PAGE, token=token, filename=Path(uploaded.filename).name, tags=tags
        )

    @app.post("/save")
    def save_pdf():
        token = request.form.get("token", "")
        path = _token_path(token)
        if not path.is_file():
            return render_template_string(
                _PAGE, token=None,
                error="That editing session expired. Please open the PDF again.")
        keys = request.form.getlist("key")
        values = request.form.getlist("value")
        fields = {k.strip(): v for k, v in zip(keys, values) if k.strip()}
        try:
            with PDFMetadataEditor(path) as editor:
                editor.replace_docinfo(fields)
                editor.save(path)
        except PDFMetadataError as exc:
            return render_template_string(
                _PAGE, token=None, error=f"Could not apply changes: {exc}")

        @after_this_request
        def _cleanup(response):
            # Remove the temp file once the download has been served. On POSIX
            # send_file has already read it; on Windows the handle may still be
            # open, in which case _sweep_stale() reclaims it on a later /open.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return response

        download_name = _safe_download_name(request.form.get("filename", ""))
        return send_file(path, as_attachment=True,
                         download_name=download_name, mimetype="application/pdf")

    return app
