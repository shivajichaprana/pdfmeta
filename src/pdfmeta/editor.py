"""Core PDF metadata read/write logic, built on pikepdf.

A PDF can carry metadata in two places:

1. The Document Information dictionary ("docinfo") — the classic
   ``/Title``, ``/Author``, ``/Subject``, ``/Keywords``, ``/Creator``,
   ``/Producer`` keys, plus any arbitrary custom keys.
2. The XMP metadata stream — an XML packet. Modern viewers prefer XMP.

This module keeps both in sync for the standard fields so that whatever
tool the user opens the PDF in shows consistent values, while still
allowing completely arbitrary custom fields in the docinfo dictionary.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pikepdf
from pikepdf.models.metadata import (
    XMP_NS_DC,
    XMP_NS_PDF,
    XMP_NS_PDFA_ID,
    XMP_NS_PDFUA_ID,
    XMP_NS_PDFX_ID,
    XMP_NS_PHOTOSHOP,
    XMP_NS_PRISM,
    XMP_NS_XMP,
    XMP_NS_XMP_MM,
    XMP_NS_XMP_RIGHTS,
    decode_pdf_date,
    encode_pdf_date,
)

# Map XMP namespace URIs -> their conventional prefix, so a raw dump can show
# ``dc:title`` instead of ``{http://purl.org/dc/elements/1.1/}title``. Unknown
# namespaces are left in full so nothing is misrepresented.
_NS_PREFIX = {
    XMP_NS_DC: "dc",
    XMP_NS_PDF: "pdf",
    XMP_NS_XMP: "xmp",
    XMP_NS_XMP_MM: "xmpMM",
    XMP_NS_XMP_RIGHTS: "xmpRights",
    XMP_NS_PDFA_ID: "pdfaid",
    XMP_NS_PDFX_ID: "pdfxid",
    XMP_NS_PDFUA_ID: "pdfuaid",
    XMP_NS_PHOTOSHOP: "photoshop",
    XMP_NS_PRISM: "prism",
}


def _pretty_qname(clark: str) -> str:
    """Convert a Clark-notation ``{uri}local`` name to ``prefix:local``.

    Known namespaces use their conventional prefix; unknown namespaces are
    left in full ``{uri}local`` form so the reader never misrepresents a tag.
    """
    if clark.startswith("{") and "}" in clark:
        uri, local = clark[1:].split("}", 1)
        prefix = _NS_PREFIX.get(uri)
        return f"{prefix}:{local}" if prefix else clark
    return clark


def _stringify(value: object) -> str:
    """Render an XMP value (which may be a list/tuple) as a readable string."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


# Map friendly field names -> the /Key used inside the PDF docinfo dict.
STANDARD_FIELDS: dict[str, str] = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
    "creator": "/Creator",
    "producer": "/Producer",
}

# Map standard docinfo keys -> XMP (prefix, local-name) so the XMP packet
# is kept in sync for the fields that have a well-known XMP equivalent.
_XMP_MAP = {
    "/Title": ("dc", "title"),
    "/Author": ("dc", "creator"),
    "/Subject": ("dc", "description"),
    "/Keywords": ("pdf", "Keywords"),
    "/Creator": ("xmp", "CreatorTool"),
    "/Producer": ("pdf", "Producer"),
}

# XMP keys whose values are array types (Seq/Bag) and must be set as a list.
# Only dc:creator (from /Author) is produced by the mapping above.
_XMP_ARRAY_KEYS = {"dc:creator"}

# Friendly aliases for the two date fields -> their docinfo key.
DATE_FIELDS: dict[str, str] = {
    "creationdate": "/CreationDate",
    "creation": "/CreationDate",
    "created": "/CreationDate",
    "moddate": "/ModDate",
    "modificationdate": "/ModDate",
    "modification": "/ModDate",
    "modified": "/ModDate",
}

# Docinfo date keys whose values must be stored in PDF date format.
_DATE_KEYS = {"/CreationDate", "/ModDate"}

# Docinfo date key -> its XMP (ISO 8601) equivalent.
_XMP_DATE_MAP = {"/CreationDate": "xmp:CreateDate", "/ModDate": "xmp:ModifyDate"}

# Human date formats accepted in addition to ISO 8601 and PDF ``D:`` strings.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%B %d, %Y",
)


class PDFMetadataError(Exception):
    """Raised for user-facing metadata errors (bad file, bad key, etc.)."""


def _parse_datetime(value: str) -> datetime:
    """Parse a human-friendly date/time string into a ``datetime``.

    Accepts ``now``, ISO 8601 (with a trailing ``Z`` allowed), and the common
    formats in ``_DATE_FORMATS``. Naive results get the local timezone attached.
    """
    v = value.strip()
    if v.lower() == "now":
        return datetime.now().astimezone()
    if v.upper().startswith("D:"):
        try:
            return decode_pdf_date(v)
        except Exception as exc:
            raise PDFMetadataError(f"Could not understand the PDF date '{value}'.") from exc

    iso = v[:-1] + "+00:00" if v.endswith(("Z", "z")) else v
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(v, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise PDFMetadataError(
            f"Could not understand the date '{value}'. Try 2026-01-15, "
            "'2026-01-15 14:30', an ISO 8601 string, a PDF date (D:2026...), "
            "or 'now'."
        )
    # Attach the local timezone if none was given, so the PDF date carries an
    # explicit UTC offset.
    return parsed if parsed.tzinfo else parsed.astimezone()


def _to_pdf_date(value: str) -> str:
    """Normalize any accepted date input into a PDF ``D:YYYYMMDD...`` string."""
    v = value.strip()
    if v.upper().startswith("D:"):
        return v  # already a PDF date string; store as-is
    encoded = encode_pdf_date(_parse_datetime(v))
    # pikepdf omits the trailing apostrophe after the minute offset; add it
    # back for full PDF-spec compliance (D:YYYYMMDDHHmmSSOHH'mm').
    if "'" in encoded and not encoded.endswith("'"):
        encoded += "'"
    return encoded


# --------------------------------------------------------------- XMP fields

# Rich XMP-only metadata fields, keyed by a friendly name.
#   kind:
#     "text"    plain text property
#     "langalt" localized text (set as a plain string)
#     "array"   ordered/unordered array (comma-separated on input)
#     "bool"    XMP boolean, stored as the text "True"/"False"
#     "date"    ISO 8601 timestamp
# The mirrored standard fields (dc:title, dc:creator, dc:description,
# pdf:Keywords, xmp:CreatorTool, pdf:Producer, xmp:CreateDate, xmp:ModifyDate)
# are handled by the docinfo path and are deliberately NOT listed here.
XMP_FIELDS: dict[str, tuple[str, str]] = {
    "copyright": ("dc:rights", "langalt"),
    "rights-marked": ("xmpRights:Marked", "bool"),
    "license": ("xmpRights:WebStatement", "text"),
    "usage-terms": ("xmpRights:UsageTerms", "langalt"),
    "owner": ("xmpRights:Owner", "array"),
    "language": ("dc:language", "array"),
    "publisher": ("dc:publisher", "array"),
    "contributor": ("dc:contributor", "array"),
    "rating": ("xmp:Rating", "text"),
    "label": ("xmp:Label", "text"),
    "metadata-date": ("xmp:MetadataDate", "date"),
    "document-id": ("xmpMM:DocumentID", "text"),
    "instance-id": ("xmpMM:InstanceID", "text"),
    "pdfa-part": ("pdfaid:part", "text"),
    "pdfa-conformance": ("pdfaid:conformance", "text"),
}

# Extra spellings that map onto a canonical XMP field name.
_XMP_ALIASES = {
    "rights": "copyright",
    "copyrighted": "rights-marked",
    "marked": "rights-marked",
    "web-statement": "license",
    "weblicense": "license",
    "languages": "language",
    "lang": "language",
    "docid": "document-id",
    "instanceid": "instance-id",
}

# Case-sensitive lookup: friendly name (lowercase) OR raw xmp key (canonical
# case) -> (xmp_key, kind). Matching is deliberately case-sensitive so that a
# capitalized name like ``Owner`` is treated as a custom docinfo field and is
# NOT shadowed by the XMP ``owner`` field — this keeps export/apply lossless.
_XMP_LOOKUP: dict[str, tuple[str, str]] = {}
for _friendly, _spec in XMP_FIELDS.items():
    _XMP_LOOKUP[_friendly] = _spec
    _XMP_LOOKUP[_spec[0]] = _spec
for _alias, _target in _XMP_ALIASES.items():
    _XMP_LOOKUP[_alias] = XMP_FIELDS[_target]

_BOOL_TRUE = {"true", "yes", "y", "1", "marked", "on"}
_BOOL_FALSE = {"false", "no", "n", "0", "unmarked", "off"}
_TRAPPED_MAP = {
    "true": "/True",
    "yes": "/True",
    "false": "/False",
    "no": "/False",
    "unknown": "/Unknown",
}


# Reverse map: raw xmp key -> friendly name (used when reporting values).
_XMP_KEY_TO_FRIENDLY = {spec[0]: friendly for friendly, spec in XMP_FIELDS.items()}


def _xmp_lookup(name: str) -> tuple[str, str] | None:
    """Return ``(xmp_key, kind)`` if ``name`` refers to a known XMP field.

    Matching is case-sensitive: the documented field names are lowercase, so
    ``owner`` maps to the XMP field while ``Owner`` is left to become a custom
    docinfo field (preserving its capitalization).
    """
    return _XMP_LOOKUP.get(name.strip())


def _xmp_friendly_name(xmp_key: str) -> str:
    """Map a raw XMP key (e.g. ``dc:rights``) back to its friendly name."""
    return _XMP_KEY_TO_FRIENDLY[xmp_key]


def _to_xmp_bool(value: str) -> str:
    """Normalize a yes/no-ish value to the XMP boolean text 'True'/'False'."""
    v = value.strip().lower()
    if v in _BOOL_TRUE:
        return "True"
    if v in _BOOL_FALSE:
        return "False"
    raise PDFMetadataError(f"Expected a yes/no value (true, false, yes, no), got '{value}'.")


def _to_trapped(value: str) -> pikepdf.Name:
    """Normalize a trapped value to the PDF name /True, /False, or /Unknown."""
    v = value.strip().lstrip("/").lower()
    if v not in _TRAPPED_MAP:
        raise PDFMetadataError(f"Trapped must be True, False, or Unknown; got '{value}'.")
    return pikepdf.Name(_TRAPPED_MAP[v])


def _normalize_key(key: str) -> str:
    """Turn a user-supplied field name into a PDF docinfo key.

    Standard fields normalize to their canonical key regardless of case or a
    leading slash, so ``title``, ``TITLE`` and ``/title`` all map to
    ``/Title``. Custom fields keep the capitalization the user supplied:
    ``Department`` and ``/Department`` both map to ``/Department``.
    """
    key = key.strip()
    # Work out the name without a leading slash so we can match standard fields.
    bare = key[1:].strip() if key.startswith("/") else key
    if not bare:
        raise PDFMetadataError("Metadata key cannot be empty.")
    low = bare.lower()
    if low in STANDARD_FIELDS:
        return STANDARD_FIELDS[low]
    if low in DATE_FIELDS:
        return DATE_FIELDS[low]
    if low == "trapped":
        return "/Trapped"
    # Custom field: keep the user's capitalization, just ensure a single slash.
    return "/" + bare


class PDFMetadataEditor:
    """Read and edit the metadata of a single PDF file.

    Example
    -------
    >>> ed = PDFMetadataEditor("in.pdf")
    >>> ed.set_field("title", "Quarterly Report")
    >>> ed.set_field("Department", "Finance")   # custom field
    >>> ed.save("out.pdf")
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise PDFMetadataError(f"File not found: {self.path}")
        if not self.path.is_file():
            raise PDFMetadataError(f"Not a file: {self.path}")
        try:
            # allow_overwriting_input lets save() write back to the same path.
            self._pdf = pikepdf.open(self.path, allow_overwriting_input=True)
        except pikepdf.PasswordError as exc:
            raise PDFMetadataError(
                f"'{self.path.name}' is password-protected; pdfmeta cannot open encrypted PDFs."
            ) from exc
        except PDFMetadataError:
            raise
        except Exception as exc:
            raise PDFMetadataError(f"Could not open PDF: {exc}") from exc

    # ------------------------------------------------------------------ read

    def read(self) -> dict[str, str]:
        """Return every metadata field currently set.

        Includes the document-info fields (keyed without the leading slash,
        e.g. ``Title``, ``Department``) plus any known rich XMP fields that are
        present (keyed by their friendly name, e.g. ``copyright``, ``language``).
        Array-valued XMP fields are returned as a comma-separated string.
        """
        result: dict[str, str] = {}
        for key, value in self._pdf.docinfo.items():
            result[str(key).lstrip("/")] = str(value)
        xmp = self._pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False)
        for friendly, (xmp_key, _kind) in XMP_FIELDS.items():
            if xmp_key in xmp:
                result[friendly] = _stringify(xmp[xmp_key])
        return result

    def read_docinfo(self) -> dict[str, str]:
        """Return EVERY entry in the Document Information dictionary, verbatim.

        Keys keep their real names without the leading slash. Nothing is
        filtered, renamed, or inferred — this is exactly what is in the file.
        """
        return {str(key).lstrip("/"): str(value) for key, value in self._pdf.docinfo.items()}

    def read_xmp(self) -> dict[str, str]:
        """Return EVERY property actually present in the XMP packet.

        Keys are ``prefix:local`` for known namespaces (``dc:title``) and the
        full ``{uri}local`` form for unknown ones. This reads the real packet,
        so it surfaces tags written by any tool, not just the ones pdfmeta
        knows how to set.
        """
        result: dict[str, str] = {}
        if "/Metadata" not in self._pdf.Root:
            return result
        xmp = self._pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False)
        for clark, value in xmp.items():
            result[_pretty_qname(clark)] = _stringify(value)
        return result

    def read_all(self) -> dict[str, dict[str, str]]:
        """Return the complete metadata read directly from the file.

        A dict with two sections, ``"Document Info"`` and ``"XMP"``, each a
        mapping of every entry actually stored in that part of the PDF.
        """
        return {"Document Info": self.read_docinfo(), "XMP": self.read_xmp()}

    def read_extra_xmp(self) -> dict[str, str]:
        """XMP properties present in the file that pdfmeta does not manage as an
        editable field — e.g. tags written by other tools (``photoshop:*``,
        ``xmpMM:History``). Useful for a read-only "nothing hidden" view."""
        managed = set(_XMP_KEY_TO_FRIENDLY)  # editable friendly XMP fields
        for prefix, local in _XMP_MAP.values():  # standard docinfo mirrors
            managed.add(f"{prefix}:{local}")
        managed.update(_XMP_DATE_MAP.values())  # xmp:CreateDate / xmp:ModifyDate
        return {k: v for k, v in self.read_xmp().items() if k not in managed}

    @property
    def page_count(self) -> int:
        """Number of pages in the PDF."""
        return len(self._pdf.pages)

    def xmp_packet(self) -> str | None:
        """Return the raw XMP XML packet exactly as stored, or ``None``."""
        if "/Metadata" not in self._pdf.Root:
            return None
        return bytes(self._pdf.Root.Metadata.read_bytes()).decode("utf-8", "replace")

    def get_field(self, name: str) -> str | None:
        """Return a single field's value, or ``None`` if it is not set."""
        xmp_spec = _xmp_lookup(name)
        if xmp_spec is not None:
            return self.read().get(_xmp_friendly_name(xmp_spec[0]))
        key = _normalize_key(name)
        if key in self._pdf.docinfo:
            return str(self._pdf.docinfo[key])
        return None

    # ----------------------------------------------------------------- write

    def set_field(self, name: str, value: str) -> None:
        """Create or update a metadata field.

        Handles four kinds of field:

        * standard docinfo text fields (Title, Author, Subject, Keywords,
          Creator, Producer) and any custom docinfo key;
        * the date fields (``created`` / ``modified`` or ``/CreationDate`` /
          ``/ModDate``), which accept a friendly date, ISO 8601, an existing
          PDF ``D:`` date, or ``now``;
        * ``trapped``, stored as the PDF name /True, /False, or /Unknown;
        * rich XMP fields such as ``copyright``, ``license``, ``language``,
          ``publisher``, ``rating``, ``document-id`` (see ``XMP_FIELDS``).
        """
        xmp_spec = _xmp_lookup(name)
        if xmp_spec is not None:
            self._set_xmp_field(xmp_spec[0], xmp_spec[1], value)
            return
        key = _normalize_key(name)
        if key == "/Trapped":
            self._pdf.docinfo[key] = _to_trapped(value)
            return
        if key in _DATE_KEYS:
            value = _to_pdf_date(value)
        self._pdf.docinfo[key] = value
        self._sync_xmp(key, value)

    def _set_xmp_field(self, xmp_key: str, kind: str, value: str) -> None:
        """Write a value to an XMP-only field, coercing to the right type."""
        if kind == "array":
            payload: str | list[str] = [part.strip() for part in value.split(",") if part.strip()]
        elif kind == "bool":
            payload = _to_xmp_bool(value)
        elif kind == "date":
            payload = _parse_datetime(value).isoformat()
        else:  # "text" or "langalt"
            payload = value
        with self._pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
            xmp[xmp_key] = payload

    def set_many(self, fields: dict[str, str]) -> None:
        """Set several fields at once from a ``{name: value}`` mapping."""
        for name, value in fields.items():
            self.set_field(name, value)

    def remove_field(self, name: str) -> bool:
        """Delete a field. Returns ``True`` if it existed, ``False`` if not."""
        xmp_spec = _xmp_lookup(name)
        if xmp_spec is not None:
            xmp_key = xmp_spec[0]
            removed = False
            with self._pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
                if xmp_key in xmp:
                    del xmp[xmp_key]
                    removed = True
            return removed
        key = _normalize_key(name)
        if key in self._pdf.docinfo:
            del self._pdf.docinfo[key]
            self._sync_xmp(key, None)
            return True
        return False

    def clear(self) -> None:
        """Remove all document-info metadata and the XMP packet."""
        for key in list(self._pdf.docinfo.keys()):
            del self._pdf.docinfo[key]
        if "/Metadata" in self._pdf.Root:
            del self._pdf.Root["/Metadata"]

    def replace_docinfo(self, fields: dict[str, str]) -> None:
        """Make the Document Information dictionary exactly ``fields``.

        Every current docinfo entry is removed (with its XMP mirror for the
        standard fields), then each supplied field is set. XMP-only properties
        that pdfmeta does not surface as docinfo (e.g. a pre-existing
        ``dc:rights``) are left untouched.
        """
        for key in list(self._pdf.docinfo.keys()):
            self.remove_field(str(key))
        for name, value in fields.items():
            name = name.strip()
            if name:
                self.set_field(name, value)

    def replace_editable(self, fields: dict[str, str]) -> None:
        """Make every *editable* tag exactly ``fields``.

        Like :meth:`replace_docinfo`, but also covers the known XMP fields
        (``copyright``, ``language``, …) so the values returned by
        :meth:`read` round-trip exactly. All current document-info entries and
        known XMP fields are cleared first, then each supplied field is set;
        raw XMP tags that pdfmeta does not manage are left untouched. Used by
        the web GUI, where the user edits everything ``read`` reports.
        """
        for key in list(self._pdf.docinfo.keys()):
            self.remove_field(str(key))
        for friendly in XMP_FIELDS:
            self.remove_field(friendly)
        for name, value in fields.items():
            name = name.strip()
            if name:
                self.set_field(name, value)

    # -------------------------------------------------------------- JSON I/O

    def export_json(self, path: str | Path) -> None:
        """Write all current metadata to a JSON file."""
        Path(path).write_text(
            json.dumps(self.read(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def import_json(self, path: str | Path, replace: bool = False) -> None:
        """Load metadata from a JSON file of ``{name: value}`` pairs.

        With ``replace=True`` all existing metadata is cleared first, so the
        PDF ends up with exactly what the JSON file contains. Every failure
        mode (missing file, unreadable file, invalid JSON, wrong shape) raises
        a clear :class:`PDFMetadataError` rather than a raw exception.
        """
        json_path = Path(path)
        if not json_path.is_file():
            raise PDFMetadataError(f"JSON file not found: {json_path}")
        try:
            raw = json_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PDFMetadataError(f"Could not read JSON file {json_path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PDFMetadataError(
                f"{json_path.name} is not valid JSON (line {exc.lineno}, "
                f"column {exc.colno}): {exc.msg}."
            ) from exc
        if not isinstance(data, dict):
            raise PDFMetadataError(
                f'{json_path.name} must be a JSON object of "Field": "value" '
                'pairs, e.g. {"Title": "My Report"}.'
            )
        clean: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)) or value is None:
                raise PDFMetadataError(
                    f'Field "{key}" in {json_path.name}: value must be text, a '
                    f"number, or true/false — not a {type(value).__name__}."
                )
            clean[str(key)] = str(value)
        if replace:
            self.clear()
        self.set_many(clean)

    def apply_json(self, path: str | Path) -> None:
        """Make the PDF's metadata match a JSON file *exactly*.

        All existing metadata is removed first, then every field in the JSON
        file is applied. After this call the PDF contains only the fields the
        JSON file specifies — nothing more. Equivalent to
        ``import_json(path, replace=True)``.
        """
        self.import_json(path, replace=True)

    # --------------------------------------------------------------- persist

    def save(self, output: str | Path | None = None) -> Path:
        """Write the PDF back out.

        If ``output`` is omitted the file is saved in place. pikepdf writes
        to a temporary file and atomically replaces the target, so an
        in-place save is safe.
        """
        target = Path(output) if output else self.path
        self._pdf.save(target)
        return target

    def close(self) -> None:
        self._pdf.close()

    def __enter__(self) -> PDFMetadataEditor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -------------------------------------------------------------- internal

    def _sync_xmp(self, key: str, value: str | None) -> None:
        """Keep the XMP packet consistent for known standard fields."""
        # Date fields map to XMP dates stored in ISO 8601.
        if key in _XMP_DATE_MAP:
            xmp_key = _XMP_DATE_MAP[key]
            xmp_value: str | None = None
            if value is not None:
                try:
                    xmp_value = decode_pdf_date(value).isoformat()
                except Exception:
                    return  # unparseable date; leave XMP untouched
            is_array = False
        else:
            mapping = _XMP_MAP.get(key)
            if mapping is None:
                return
            prefix, local = mapping
            xmp_key = f"{prefix}:{local}"
            xmp_value = value
            is_array = xmp_key in _XMP_ARRAY_KEYS
        try:
            # update_docinfo=False is critical: with the default (True), pikepdf
            # reverse-syncs the XMP packet back onto the docinfo dict on exit,
            # which would wipe any pre-existing docinfo fields not present in
            # our freshly written XMP. docinfo is our source of truth.
            with self._pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as xmp:
                if xmp_value is None:
                    if xmp_key in xmp:
                        del xmp[xmp_key]
                elif is_array:
                    xmp[xmp_key] = [xmp_value]
                else:
                    xmp[xmp_key] = xmp_value
        except Exception:
            # XMP is best-effort; docinfo is the source of truth. Never let
            # an XMP hiccup block a metadata write.
            pass
