"""Property-based tests (Hypothesis) for the fiddly bits: date parsing and the
metadata round-trip. These fuzz many inputs to catch edge cases plain
example-based tests miss."""

import tempfile
from datetime import datetime
from pathlib import Path

import pikepdf
from hypothesis import given
from hypothesis import strategies as st
from pikepdf.models.metadata import decode_pdf_date

from pdfmeta.editor import PDFMetadataEditor, _parse_datetime, _to_pdf_date

_DATETIMES = st.datetimes(
    min_value=datetime(1990, 1, 1),
    max_value=datetime(2099, 12, 31),
)

# Custom-field key suffix: ASCII letters/digits/underscore only, so it is a
# valid PDF name and never collides with a reserved field name.
_KEY_SUFFIX = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=1,
    max_size=20,
)

# Values: any unicode text except control characters and surrogates.
_VALUE = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
    min_size=1,
    max_size=60,
)


@given(_DATETIMES)
def test_parse_datetime_roundtrip(dt):
    """A formatted date parses back to the same moment (to the second)."""
    parsed = _parse_datetime(dt.strftime("%Y-%m-%d %H:%M:%S"))
    assert parsed.replace(tzinfo=None) == dt.replace(microsecond=0)


@given(_DATETIMES)
def test_pdf_date_roundtrip(dt):
    """encode -> PDF ``D:`` string -> decode returns the same moment."""
    back = decode_pdf_date(_to_pdf_date(dt.strftime("%Y-%m-%d %H:%M:%S")))
    assert back.replace(tzinfo=None) == dt.replace(microsecond=0)


@given(_KEY_SUFFIX, _VALUE)
def test_custom_field_roundtrip(suffix, value):
    """Any custom field name/value written is read back unchanged."""
    key = "Custom_" + suffix
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "p.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(200, 200))
        pdf.save(path)
        pdf.close()
        with PDFMetadataEditor(path) as ed:
            ed.set_field(key, value)
            ed.save()
        with PDFMetadataEditor(path) as ed:
            assert ed.read_docinfo()[key] == value
