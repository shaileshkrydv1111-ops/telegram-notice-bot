"""PDF inspection and high-quality rendering to images.

Uses PyMuPDF (fitz) which is pure-Python-installable (no poppler/system
dependency needed), making it equally easy to run on Replit and on a bare
Ubuntu VPS.
"""

from __future__ import annotations

import io

import fitz  # PyMuPDF

import config
from logger_setup import log


def page_count(pdf_bytes: bytes) -> int:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def render_pages_to_images(pdf_bytes: bytes, dpi: int | None = None) -> list[bytes]:
    """Render every page of a PDF to a high-quality PNG image.

    Returns a list of PNG byte strings, one per page, in page order.
    """
    dpi = dpi or config.PDF_RENDER_DPI
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    images: list[bytes] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            buffer = io.BytesIO(pixmap.tobytes("png"))
            images.append(buffer.getvalue())
    log.debug("Rendered %d page(s) to PNG at %d DPI", len(images), dpi)
    return images


def is_valid_pdf(data: bytes) -> bool:
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count > 0
    except Exception:  # noqa: BLE001 - any parse failure means "not a usable pdf"
        return False
