"""Browser end-to-end tests for the GUI — they exercise the real JavaScript
(drag-drop/upload auto-submit, the Add-tag button, dark mode) in a headless
Chromium.

Run them in CI (or locally) with a real browser::

    pip install -e ".[gui,e2e]"
    playwright install --with-deps chromium
    pytest tests/e2e

They skip automatically wherever Playwright or its browser isn't installed, so
the normal test suite is unaffected.
"""

import re
import threading

import pytest

pw = pytest.importorskip("playwright.sync_api")

import pikepdf
from werkzeug.serving import make_server

from pdfmeta.webapp import create_app


@pytest.fixture(scope="module")
def server():
    app = create_app()
    srv = make_server("127.0.0.1", 0, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # browser or system deps missing
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / "e.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.docinfo["/Title"] = "Hello"
    pdf.save(path)
    pdf.close()
    return str(path)


def test_upload_then_add_row(page, server, sample_pdf):
    page.goto(server)
    page.set_input_files("#pdfInput", sample_pdf)  # change event auto-submits
    page.wait_for_selector("#rows")
    before = page.locator("#rows tr").count()
    page.get_by_role("button", name="+ Add tag").click()
    assert page.locator("#rows tr").count() == before + 1


def test_dark_mode_applies(page, server):
    page.emulate_media(color_scheme="dark")
    page.goto(server)
    bg = page.eval_on_selector("body", "el => getComputedStyle(el).backgroundColor")
    channels = [int(n) for n in re.findall(r"\d+", bg)[:3]]
    assert sum(channels) < 200  # a dark background
