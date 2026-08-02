"""Parsers for every supported import format (issue #85).

Keyed by *detected* media type, not by filename. A file called `notes.txt`
that is really a PDF should be parsed as a PDF or refused, not fed to the text
parser as mojibake — and on the other side, a `.epub` renamed by a download
manager should still work. Detection reads the leading bytes; the extension is
only consulted for the text formats, which have no magic number to read.

Every parser is bounded. The limits live in the domain module so a new format
cannot invent its own, and they are refusals rather than truncations: silently
importing the first fraction of a document looks like success.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile

from app.domain.services.documents import (
    MAX_BYTES,
    MAX_DECOMPRESSION_RATIO,
    DocumentStructureError,
    DocumentTooLargeError,
    ParsedDocument,
    build_document,
)

# Leading bytes that identify a format regardless of what it is called.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    # Both EPUB and DOCX are zip containers, so the signature is the same and
    # the container has to be opened to tell them apart. See _detect_zip.
    (b"PK\x03\x04", "application/zip"),
)

_EXTENSION_TYPES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "html": "text/html",
    "htm": "text/html",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def detect_media_type(data: bytes, filename: str) -> str:
    """What this file actually is.

    Content first, extension only as a fallback for formats that have no
    signature. A mismatch between the two is not reported as an error: the
    content is simply believed, because a renamed file is a user's mistake to
    absorb rather than to be lectured about.
    """
    for signature, media_type in _MAGIC:
        if data.startswith(signature):
            if media_type == "application/zip":
                return _detect_zip(data)
            return media_type

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    return _EXTENSION_TYPES.get(suffix, "text/plain")


def _detect_zip(data: bytes) -> str:
    """Tell EPUB from DOCX by what the container holds."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile as exc:
        raise DocumentStructureError("file is not a readable archive") from exc
    if "mimetype" in names or any(n.endswith(".opf") for n in names):
        return "application/epub+zip"
    if "word/document.xml" in names:
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raise DocumentStructureError("archive is neither an EPUB nor a DOCX")


def _guard_archive(data: bytes) -> zipfile.ZipFile:
    """Open a zip container, refusing one that would decompress unreasonably.

    EPUB and DOCX are both zip archives, so a small upload can declare an
    enormous decompressed size. The ratio is computed from the header rather
    than by decompressing and measuring, which is the whole point — measuring
    would mean already having done the damage.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentStructureError("file is not a readable archive") from exc

    declared = sum(info.file_size for info in archive.infolist())
    if len(data) and declared / len(data) > MAX_DECOMPRESSION_RATIO:
        raise DocumentStructureError(
            f"archive expands {declared // max(len(data), 1)}x, beyond the "
            f"{MAX_DECOMPRESSION_RATIO}x limit"
        )
    if declared > MAX_BYTES * MAX_DECOMPRESSION_RATIO:
        raise DocumentStructureError("archive contents exceed the supported size")
    return archive


# --- Per-format parsers ----------------------------------------------------


def _parse_text(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    return build_document(filename, media_type, [("Document", text)])


def _parse_markdown(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    """Split on headings, so a section label is something a reader recognises."""
    text = data.decode("utf-8-sig", errors="replace")
    sections: list[tuple[str, str]] = []
    label = "Introduction"
    buffer: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            if buffer:
                sections.append((label, "\n".join(buffer)))
                buffer = []
            label = heading.group(1).strip() or label
            continue
        buffer.append(line)
    if buffer:
        sections.append((label, "\n".join(buffer)))
    return build_document(filename, media_type, sections or [("Document", text)])


def _parse_html(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data.decode("utf-8-sig", errors="replace"), "html.parser")
    # Script and style contain code, not prose. Left in, they produce
    # "candidates" like `getElementById`.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return build_document(filename, media_type, [("Document", soup.get_text(" "))])


_CUE_TIMING = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")


def _parse_subtitles(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    """SRT and VTT alike: keep the spoken text, drop cue numbers and timings.

    Subtitle lines break on display timing rather than on grammar, so cues are
    joined into one run of text and re-split into sentences afterwards.
    Treating each cue as a sentence would produce half-sentence excerpts.
    """
    text = data.decode("utf-8-sig", errors="replace")
    spoken: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or _CUE_TIMING.match(stripped):
            continue
        if stripped.upper().startswith(("WEBVTT", "NOTE ", "STYLE")):
            continue
        # Positioning and karaoke markup, which are not words anyone is
        # learning.
        spoken.append(re.sub(r"<[^>]+>", "", stripped))
    return build_document(filename, media_type, [("Subtitles", " ".join(spoken))])


def _parse_pdf(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise DocumentStructureError(f"PDF could not be read: {exc}") from exc

    if reader.is_encrypted:
        # Not attempted with an empty password: a document someone encrypted
        # should fail loudly rather than be opened by guessing.
        raise DocumentStructureError("PDF is encrypted and cannot be imported")

    sections: list[tuple[str, str]] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            sections.append((f"Page {number}", page.extract_text() or ""))
        except Exception as exc:  # noqa: BLE001 - one unreadable page is not a failed import
            # A page that will not extract is skipped and counted by
            # build_document, which reports it as a warning. Scanned pages hit
            # this constantly and are the reason OCR is a separate issue (#84).
            sections.append((f"Page {number}", ""))
            del exc
    return build_document(filename, media_type, sections)


def _parse_epub(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    import warnings

    from bs4 import BeautifulSoup

    _guard_archive(data)
    with warnings.catch_warnings():
        # ebooklib warns about future defaults on every open; it is noise here.
        warnings.simplefilter("ignore")
        import ebooklib
        from ebooklib import epub

        # ebooklib only reads from a path, not a file object, so the upload is
        # spilled to a temporary file. Deleted on the way out whatever happens:
        # an import that failed halfway must not leave someone's book on disk.
        import os
        import tempfile

        handle, path = tempfile.mkstemp(suffix=".epub")
        try:
            with os.fdopen(handle, "wb") as spilled:
                spilled.write(data)
            try:
                book = epub.read_epub(path)
            except Exception as exc:  # noqa: BLE001 - library raises bare Exception
                raise DocumentStructureError(f"EPUB could not be read: {exc}") from exc

            # Chapter names come from the table of contents where there is
            # one. A <title> element is not reliable: writers strip it, and
            # ebooklib does not repopulate item.title on read.
            toc_titles: dict[str, str] = {}
            for entry in getattr(book, "toc", []) or []:
                link = entry[0] if isinstance(entry, tuple) else entry
                href = getattr(link, "href", None)
                title = getattr(link, "title", None)
                if href and title:
                    toc_titles[href.split("#")[0]] = title

            sections: list[tuple[str, str]] = []
            for number, item in enumerate(book.get_items_of_type(ebooklib.ITEM_DOCUMENT), start=1):
                name = item.get_name()
                # The navigation document is a table of contents, not prose.
                # Its links would otherwise become vocabulary candidates.
                if name.endswith("nav.xhtml") or item.get_id() == "nav":
                    continue
                soup = BeautifulSoup(item.get_content(), "html.parser")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                heading = soup.find(["h1", "h2"])
                title = (
                    toc_titles.get(name)
                    or (soup.title.string if soup.title and soup.title.string else None)
                    or (heading.get_text(" ").strip() if heading else None)
                    or f"Chapter {number}"
                )
                sections.append((title.strip(), soup.get_text(" ")))
        finally:
            os.unlink(path)
    return build_document(filename, media_type, sections)


def _parse_docx(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    import docx

    _guard_archive(data)
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - library raises several types
        raise DocumentStructureError(f"DOCX could not be read: {exc}") from exc

    sections: list[tuple[str, str]] = []
    label = "Document"
    buffer: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.style is not None and paragraph.style.name.startswith("Heading"):
            if buffer:
                sections.append((label, "\n".join(buffer)))
                buffer = []
            label = paragraph.text.strip() or label
            continue
        if paragraph.text.strip():
            buffer.append(paragraph.text)
    if buffer:
        sections.append((label, "\n".join(buffer)))
    return build_document(filename, media_type, sections)


def _parse_csv(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    """Tabular imports are records, not prose, so every cell becomes text.

    Kept in the registry so one entry point serves every format; the record
    oriented path in the imports router still handles column mapping.
    """
    text = data.decode("utf-8-sig", errors="replace")
    delimiter = "\t" if media_type.endswith("tab-separated-values") else ","
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise DocumentStructureError(f"delimited file could not be read: {exc}") from exc
    return build_document(filename, media_type, [("Rows", " ".join(" ".join(r) for r in rows))])


def _parse_json(data: bytes, filename: str, media_type: str) -> ParsedDocument:
    try:
        payload = json.loads(data.decode("utf-8-sig", errors="replace"))
    except json.JSONDecodeError as exc:
        raise DocumentStructureError(f"JSON could not be read: {exc}") from exc
    return build_document(filename, media_type, [("Document", json.dumps(payload))])


PARSERS = {
    "text/plain": _parse_text,
    "text/markdown": _parse_markdown,
    "text/html": _parse_html,
    "text/csv": _parse_csv,
    "text/tab-separated-values": _parse_csv,
    "application/json": _parse_json,
    "application/x-subrip": _parse_subtitles,
    "text/vtt": _parse_subtitles,
    "application/pdf": _parse_pdf,
    "application/epub+zip": _parse_epub,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _parse_docx,
}

SUPPORTED_MEDIA_TYPES = frozenset(PARSERS)


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    """Detect the format and parse it, within the declared bounds.

    Size is checked before anything else touches the bytes. A parser that is
    handed a 500 MB file has already lost — the refusal has to come first.
    """
    if len(data) > MAX_BYTES:
        raise DocumentTooLargeError(
            f"file is {len(data) // (1024 * 1024)} MB, above the "
            f"{MAX_BYTES // (1024 * 1024)} MB limit"
        )
    if not data:
        raise DocumentStructureError("file is empty")

    media_type = detect_media_type(data, filename)
    parser = PARSERS.get(media_type)
    if parser is None:
        raise DocumentStructureError(f"{media_type} is not a supported import format")
    return parser(data, filename, media_type)
