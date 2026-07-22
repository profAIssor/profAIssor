"""Extract slide text from .pdf files (one page = one slide)."""
from io import BytesIO
from typing import List

from pypdf import PdfReader

from schemas import Slide


def extract_slides(file_bytes: bytes) -> List[Slide]:
    """Parse a PDF and return one Slide per page.

    Presentation PDFs are typically exported one slide per page, so each page
    maps cleanly onto a Slide. Pages with no extractable text (e.g. scanned or
    image-only slides) yield an empty Slide the user can fill in manually,
    rather than failing the whole upload.
    """
    reader = PdfReader(BytesIO(file_bytes))
    slides: List[Slide] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        # Collapse runs of blank lines that PDF extraction tends to leave behind.
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        slides.append(Slide(index=i, text=text))
    return slides
