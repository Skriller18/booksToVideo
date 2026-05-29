from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .ai_backend import extract_ai
from .heading_detector import extract_from_headings
from .models import BookHierarchy, Chapter, to_dict
from .toc_detector import extract_from_toc


def extract_hierarchy(
    pdf_path: str | Path,
    api_key: str | None = None,
    force_method: str | None = None,
) -> BookHierarchy:
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        import fitz
    except ImportError:
        raise RuntimeError(
            "PyMuPDF (fitz) is required. Install it with: pip install PyMuPDF"
        )

    doc = fitz.open(str(pdf_path))
    page_count = doc.page_count
    source_pdf = pdf_path.name

    try:
        if force_method == "toc":
            return _try_toc(source_pdf, doc, page_count)
        if force_method == "headings":
            return _try_headings(source_pdf, doc, page_count)
        if force_method == "ai":
            return _try_ai(source_pdf, doc, page_count, api_key)

        result = _try_toc(source_pdf, doc, page_count)
        if result.extraction_confidence >= 1.0:
            return result

        text_chars = sum(len(doc[i].get_text()) for i in range(page_count))
        if text_chars < page_count * 30:
            if api_key:
                return _try_ai(source_pdf, doc, page_count, api_key)
            return BookHierarchy(
                book_title=_infer_title(source_pdf),
                source_pdf=source_pdf,
                extraction_method="none",
                extraction_confidence=0.0,
                page_count=page_count,
                chapters=[],
                extra={
                    "warning": "Scanned or image-only PDF. No extractable text found.",
                    "recommendation": "Use OCR (e.g., Datalab) or set --gemini-key for AI extraction with image mode.",
                },
            )

        result = _try_headings(source_pdf, doc, page_count)
        if result.extraction_confidence >= 0.9:
            return result

        if api_key:
            return _try_ai(source_pdf, doc, page_count, api_key)
        return result
    finally:
        doc.close()


def _try_toc(source_pdf: str, doc: Any, page_count: int) -> BookHierarchy:
    toc = doc.get_toc()
    if not toc:
        return BookHierarchy(
            book_title=_infer_title(source_pdf),
            source_pdf=source_pdf,
            extraction_method="toc",
            extraction_confidence=0.0,
            page_count=page_count,
            chapters=[],
            extra={"toc_status": "empty"},
        )

    chapters, confidence = extract_from_toc(source_pdf, toc, page_count, doc)
    return BookHierarchy(
        book_title=_infer_title(source_pdf, chapters=chapters),
        source_pdf=source_pdf,
        extraction_method="toc",
        extraction_confidence=confidence,
        page_count=page_count,
        chapters=chapters,
        extra={"toc_entries": len(toc)},
    )


def _try_headings(source_pdf: str, doc: Any, page_count: int) -> BookHierarchy:
    chapters, confidence = extract_from_headings(source_pdf, doc, page_count)
    return BookHierarchy(
        book_title=_infer_title(source_pdf, chapters=chapters),
        source_pdf=source_pdf,
        extraction_method="headings",
        extraction_confidence=confidence,
        page_count=page_count,
        chapters=chapters,
    )


def _try_ai(
    source_pdf: str,
    doc: Any,
    page_count: int,
    api_key: str | None,
) -> BookHierarchy:
    chapters, confidence = extract_ai(source_pdf, doc, page_count, api_key=api_key)
    _fill_topic_text(chapters, doc)
    return BookHierarchy(
        book_title=_infer_title(source_pdf, chapters=chapters),
        source_pdf=source_pdf,
        extraction_method="ai",
        extraction_confidence=confidence,
        page_count=page_count,
        chapters=chapters,
    )


def _fill_topic_text(chapters: list[Chapter], doc: Any) -> None:
    for ch in chapters:
        for topic in ch.topics:
            if topic.text:
                continue
            parts = []
            start = max(0, topic.page_start - 1)
            end = min(topic.page_end - 1, doc.page_count - 1)
            for i in range(start, end + 1):
                text = doc[i].get_text().strip()
                if text:
                    parts.append(text)
            topic.text = "\n\n".join(parts)


def _infer_title(
    source_pdf: str,
    chapters: list[Chapter] | None = None,
) -> str:
    if chapters and chapters[0].title:
        return chapters[0].title
    stem = Path(source_pdf).stem
    return stem.replace("_", " ").replace("-", " ").title()
