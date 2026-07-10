"""A small local web GUI for viewing and editing PDF metadata.

Runs entirely on your own machine — the PDF never leaves your computer. Upload
a PDF, edit its metadata tags (add / change / delete), click Modify, and
download the result. It reuses :class:`pdfmeta.editor.PDFMetadataEditor`, so the
edits behave exactly like the command-line tool.

Flask is an optional dependency; install it with ``pip install "pdfmeta[gui]"``.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import tempfile
import time
from pathlib import Path

from flask import (
    Flask,
    Response,
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


def _serve_and_cleanup(path: Path, filename: str) -> Response:
    """Send the edited PDF as a download, then delete the temp file."""

    @after_this_request
    def _cleanup(response: Response) -> Response:
        # send_file has read the file on POSIX; on Windows the handle may still
        # be open, in which case _sweep_stale() reclaims it on a later /open.
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        return response

    return send_file(
        path,
        as_attachment=True,
        download_name=_safe_download_name(filename),
        mimetype="application/pdf",
    )


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
  .drop { display: block; text-align: center; padding: 38px 30px; border: 2px dashed var(--line);
          border-radius: 10px; cursor: pointer; transition: background .12s, border-color .12s; }
  .drop:hover { border-color: #b9c0ca; }
  .drop.over { border-color: var(--brand); background: #f0f6ff; }
  .drop-emoji { font-size: 26px; }
  .visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0;
          margin: -1px; overflow: hidden; clip: rect(0 0 0 0); border: 0; }
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
  .btn.danger { background: transparent; color: var(--danger); border: 1px solid #e6b3ad; }
  .btn.danger:hover { background: #fdecea; }
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
    <form id="uploadForm" method="post" action="{{ url_for('open_pdf') }}"
          enctype="multipart/form-data">
      <label id="drop" class="drop" for="pdfInput">
        <div class="drop-emoji" aria-hidden="true">⬆️</div>
        <p><strong>Drag a PDF here</strong> — or click to choose a file</p>
        <input id="pdfInput" class="visually-hidden" type="file" name="pdf"
               accept="application/pdf,.pdf" required>
        <p id="fname" class="muted">No file chosen yet</p>
      </label>
      <p style="text-align:center; margin-top:16px;">
        <button class="btn primary" type="submit">Open</button>
      </p>
      <p class="muted">Nothing is uploaded to the internet. Files are processed
        on your machine only.</p>
    </form>
  </div>
  {% else %}
  <div class="card">
    <p class="muted">Editing <strong>{{ filename }}</strong> — these are the
      document's metadata tags (Document Info and XMP). Change a value, delete a
      row, or add a new tag (e.g. <code>copyright</code>, <code>language</code>),
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
        <button type="submit" class="btn danger"
                formaction="{{ url_for('scrub_pdf') }}"
                onclick="return confirm('Remove ALL metadata and download a clean copy?');">
          Remove all metadata
        </button>
        <a class="muted" href="{{ url_for('index') }}">Start over</a>
      </div>
    </form>
  </div>
  <p class="muted">The standard tags are also written to the PDF's XMP stream so
    every viewer stays consistent. Your original file is untouched — this
    downloads a new edited copy.</p>
  {% if extra %}
  <div class="card">
    <p class="muted" style="margin-top:0;">Other XMP tags found in this file
      (written by another tool — shown read-only):</p>
    <table>
      <tbody>
        {% for k, v in extra %}
        <tr><td class="k"><code>{{ k }}</code></td><td>{{ v }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
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

  (function () {
    var drop = document.getElementById('drop');
    if (!drop) return;
    var input = document.getElementById('pdfInput');
    var fname = document.getElementById('fname');
    var form = document.getElementById('uploadForm');
    function show() {
      if (input.files && input.files.length) {
        fname.textContent = input.files[0].name;
      }
    }
    ['dragenter', 'dragover'].forEach(function (e) {
      drop.addEventListener(e, function (ev) {
        ev.preventDefault();
        drop.classList.add('over');
      });
    });
    ['dragleave', 'drop'].forEach(function (e) {
      drop.addEventListener(e, function (ev) {
        ev.preventDefault();
        drop.classList.remove('over');
      });
    });
    drop.addEventListener('drop', function (ev) {
      if (ev.dataTransfer.files && ev.dataTransfer.files.length) {
        input.files = ev.dataTransfer.files;
        show();
        form.submit();
      }
    });
    input.addEventListener('change', function () { show(); form.submit(); });
  })();
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
    def open_pdf() -> str:
        uploaded = request.files.get("pdf")
        if uploaded is None or not uploaded.filename:
            return render_template_string(_PAGE, token=None, error="Please choose a PDF file.")
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _sweep_stale()  # clear out any abandoned uploads
        token = secrets.token_hex(16)
        path = _UPLOAD_DIR / f"{token}.pdf"
        uploaded.save(path)
        try:
            with PDFMetadataEditor(path) as editor:
                tags = list(editor.read().items())
                extra = list(editor.read_extra_xmp().items())
        except PDFMetadataError as exc:
            path.unlink(missing_ok=True)
            return render_template_string(_PAGE, token=None, error=str(exc))
        return render_template_string(
            _PAGE, token=token, filename=Path(uploaded.filename).name, tags=tags, extra=extra
        )

    @app.post("/save")
    def save_pdf() -> Response | str:
        token = request.form.get("token", "")
        path = _token_path(token)
        if not path.is_file():
            return render_template_string(
                _PAGE, token=None, error="That editing session expired. Please open the PDF again."
            )
        keys = request.form.getlist("key")
        values = request.form.getlist("value")
        fields = {k.strip(): v for k, v in zip(keys, values) if k.strip()}
        try:
            with PDFMetadataEditor(path) as editor:
                editor.replace_editable(fields)
                editor.save(path)
        except PDFMetadataError as exc:
            return render_template_string(
                _PAGE, token=None, error=f"Could not apply changes: {exc}"
            )
        return _serve_and_cleanup(path, request.form.get("filename", ""))

    @app.post("/scrub")
    def scrub_pdf() -> Response | str:
        token = request.form.get("token", "")
        path = _token_path(token)
        if not path.is_file():
            return render_template_string(
                _PAGE, token=None, error="That editing session expired. Please open the PDF again."
            )
        try:
            with PDFMetadataEditor(path) as editor:
                editor.clear()
                editor.save(path)
        except PDFMetadataError as exc:
            return render_template_string(
                _PAGE, token=None, error=f"Could not clean the file: {exc}"
            )
        return _serve_and_cleanup(path, request.form.get("filename", ""))

    return app
