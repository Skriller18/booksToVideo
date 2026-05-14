from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Iterable


TEXT_KEYS = ("text", "html", "markdown", "content")
CHILD_KEYS = ("children", "blocks", "items", "elements")
HEADING_TYPES = {"title", "sectionheader", "heading", "header"}


def normalize_datalab_convert_result(
    datalab_result: dict[str, Any],
    source_pdf: str,
    output_dir: Path,
    chapter_id: str | None = None,
    chapter_title: str | None = None,
) -> dict[str, Any]:
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    document_json = _document_json(datalab_result)
    extracted_images = _save_images(datalab_result, assets_dir)
    pages = _normalize_pages(document_json, datalab_result)
    title = chapter_title or _infer_title(document_json, pages, source_pdf)
    normalized_chapter_id = chapter_id or _slug(title)
    topics = _build_page_topics(pages, extracted_images)

    if not topics:
        full_text = " ".join(page["text"] for page in pages if page["text"]).strip()
        topics = [
            {
                "topic_id": "topic_01",
                "title": title,
                "source_pages": [page["page_number"] for page in pages],
                "text": full_text,
                "learning_goal": f"Students understand the main ideas in {title}.",
                "illustrations": extracted_images,
            }
        ]

    return {
        "chapter_id": normalized_chapter_id,
        "title": title,
        "source_pdf": source_pdf,
        "provider": "datalab",
        "provider_metadata": {
            "status": datalab_result.get("status"),
            "page_count": datalab_result.get("page_count"),
            "parse_quality_score": datalab_result.get("parse_quality_score"),
            "cost_breakdown": datalab_result.get("cost_breakdown"),
        },
        "pages": pages,
        "topics": topics,
    }


def _document_json(datalab_result: dict[str, Any]) -> dict[str, Any]:
    value = datalab_result.get("json")
    if isinstance(value, dict):
        return value
    return datalab_result


def _normalize_pages(document_json: dict[str, Any], datalab_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_pages = document_json.get("pages")
    if not isinstance(raw_pages, list):
        raw_pages = _pages_from_markdown(datalab_result.get("markdown", ""))

    pages: list[dict[str, Any]] = []
    for index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, dict):
            raw_page = {"text": str(raw_page)}
        page_number = _page_number(raw_page, index)
        blocks = _page_blocks(raw_page)
        text = _collect_text(raw_page)
        heading = _first_heading(blocks) or _first_line(text) or f"Page {page_number}"
        pages.append(
            {
                "page_number": page_number,
                "title": heading,
                "text": text,
                "blocks": blocks,
            }
        )
    return pages


def _save_images(datalab_result: dict[str, Any], assets_dir: Path) -> list[dict[str, Any]]:
    images = datalab_result.get("images") or {}
    if not isinstance(images, dict):
        return []

    extracted: list[dict[str, Any]] = []
    for index, (filename, encoded) in enumerate(images.items(), start=1):
        if not isinstance(encoded, str):
            continue
        suffix = Path(filename).suffix or ".png"
        safe_name = f"illustration_{index:03d}{suffix}"
        output_path = assets_dir / safe_name
        output_path.write_bytes(_decode_base64_image(encoded))
        extracted.append(
            {
                "illustration_id": f"illustration_{index:03d}",
                "path": str(output_path),
                "caption": _caption_from_filename(filename),
                "page_number": _page_number_from_filename(filename),
                "source_filename": filename,
            }
        )
    return extracted


def _build_page_topics(
    pages: list[dict[str, Any]],
    extracted_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topics: list[dict[str, Any]] = []
    for index, page in enumerate(pages, start=1):
        text = page.get("text", "").strip()
        if not text:
            continue
        page_number = page["page_number"]
        illustrations = [
            image
            for image in extracted_images
            if image.get("page_number") in (None, page_number)
        ]
        title = page.get("title") or f"Page {page_number}"
        topics.append(
            {
                "topic_id": f"topic_{index:02d}",
                "title": title,
                "source_pages": [page_number],
                "text": text,
                "learning_goal": f"Students understand the main idea of {title}.",
                "illustrations": illustrations,
            }
        )
    return topics


def _pages_from_markdown(markdown: str) -> list[dict[str, Any]]:
    if not markdown.strip():
        return []
    parts = re.split(r"\n\s*---+\s*\n", markdown)
    return [{"text": part.strip()} for part in parts if part.strip()]


def _page_number(raw_page: dict[str, Any], index: int) -> int:
    for key in ("page_number", "page", "page_id", "page_idx", "id"):
        value = raw_page.get(key)
        if isinstance(value, int):
            return value + 1 if key in {"page_id", "page_idx"} and value == index else value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return index + 1


def _page_blocks(raw_page: dict[str, Any]) -> list[dict[str, Any]]:
    for key in CHILD_KEYS:
        value = raw_page.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _collect_text(value: Any) -> str:
    parts: list[str] = []
    _walk_text(value, parts)
    return _clean_text(" ".join(parts))


def _walk_text(value: Any, parts: list[str]) -> None:
    if isinstance(value, dict):
        for key in TEXT_KEYS:
            text = value.get(key)
            if isinstance(text, str):
                parts.append(_strip_markup(text))
        for key in CHILD_KEYS:
            child = value.get(key)
            if isinstance(child, list):
                _walk_text(child, parts)
    elif isinstance(value, list):
        for item in value:
            _walk_text(item, parts)


def _first_heading(blocks: Iterable[dict[str, Any]]) -> str:
    for block in blocks:
        block_type = str(block.get("block_type") or block.get("type") or "").lower()
        if block_type in HEADING_TYPES:
            text = _collect_text(block)
            if text:
                return text
    return ""


def _infer_title(document_json: dict[str, Any], pages: list[dict[str, Any]], source_pdf: str) -> str:
    for key in ("title", "document_title"):
        value = document_json.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for page in pages:
        if page.get("title"):
            return str(page["title"])
    return Path(source_pdf).stem.replace("_", " ").replace("-", " ").title()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:80]
    words = text.split()
    return " ".join(words[:10])


def _decode_base64_image(encoded: str) -> bytes:
    if "," in encoded and encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    return base64.b64decode(encoded)


def _caption_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = re.sub(r"[_-]+", " ", stem).strip()
    return cleaned or "Extracted textbook illustration"


def _page_number_from_filename(filename: str) -> int | None:
    match = re.search(r"(?:page|p)[_-]?(\d+)", filename, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _strip_markup(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "chapter"

