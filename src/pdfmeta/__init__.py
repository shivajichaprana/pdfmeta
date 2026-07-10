"""pdfmeta — a small CLI + library to view and edit PDF metadata.

Supports standard document-info fields (Title, Author, Subject, Keywords,
Creator, Producer), the creation/modification dates, the Trapped flag, a set
of rich XMP fields (copyright, rights, language, publisher, rating, IDs, and
more), and arbitrary custom key/value metadata fields.
"""

from .editor import (
    DATE_FIELDS,
    PDFMetadataEditor,
    STANDARD_FIELDS,
    XMP_FIELDS,
)

__all__ = ["PDFMetadataEditor", "STANDARD_FIELDS", "DATE_FIELDS", "XMP_FIELDS"]
__version__ = "0.1.0"
