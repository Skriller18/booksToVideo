from __future__ import annotations

import json
import os
from typing import Any

from .models import Chapter, Topic


_AI_PROMPT = """You are given a textbook PDF extracted page by page.

Task: Identify the chapter/topic hierarchy of this book.

For each page, I provide the page number and extracted text. Identify:
1. Chapters: major divisions (e.g., Chapter 1, Unit 2, Lesson 3).
2. Topics under each chapter: sub-sections within that chapter (e.g., "Reading Comprehension", "Vocabulary", "Grammar", "Writing").

Rules:
- A chapter typically starts on a new page with a prominent heading.
- Topics are sub-divisions within a chapter, often marked by bold/section headings.
- If you cannot detect chapters, treat the entire document as one chapter.
- Map each chapter and topic to its starting page (1-indexed).

Return valid JSON only, matching this schema:
{
  "book_title": "string",
  "chapters": [
    {
      "chapter_number": 1,
      "title": "string",
      "page_start": 1,
      "topics": [
        {
          "topic_number": 1,
          "title": "string",
          "page_start": 1
        }
      ]
    }
  ]
}

Do NOT include any text outside the JSON. Do NOT use markdown fences (```)."""


def extract_ai(
    source_pdf: str,
    doc: Any,
    page_count: int,
    api_key: str | None = None,
    model: str = "gemini-2.5-flash",
) -> tuple[list[Chapter], float]:
    key = api_key or _google_api_key()
    if not key:
        raise RuntimeError(
            "No Gemini API key found. Set GEMINI_API_KEY, GOOGLE_API_KEY, "
            "or VERTEX_API_KEY in the environment, or pass --gemini-key."
        )

    pages_data = _build_pages_context(doc, page_count)
    prompt = f"{_AI_PROMPT}\n\nDocument info: {page_count} pages, source: {source_pdf}\n\nPages:\n{pages_data}"

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required for AI extraction. Run: pip install google-genai"
        ) from exc

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = getattr(response, "text", "") or ""
    payload = json.loads(raw)

    return _parse_ai_response(payload, page_count), 0.85


def _build_pages_context(doc: Any, page_count: int) -> str:
    lines = []
    for i in range(page_count):
        text = doc[i].get_text().strip()
        if text:
            preview = text[:2000]
            lines.append(f"=== Page {i + 1} ===\n{preview}")
    return "\n\n".join(lines)


def _parse_ai_response(payload: dict[str, Any], page_count: int) -> list[Chapter]:
    chapters: list[Chapter] = []
    raw_chapters = payload.get("chapters", [])
    if not isinstance(raw_chapters, list):
        raw_chapters = []

    for ch_index, raw_ch in enumerate(raw_chapters, start=1):
        if not isinstance(raw_ch, dict):
            continue
        ch_title = str(raw_ch.get("title") or f"Chapter {ch_index}").strip()
        ch_page = int(raw_ch.get("page_start", 1))
        chapter_id = _slug(ch_title) or f"ch_{ch_index:02d}"

        next_page = None
        if ch_index < len(raw_chapters):
            next_page = raw_chapters[ch_index].get("page_start", page_count + 1)
            if isinstance(next_page, (int, float)):
                next_page = int(next_page)
            else:
                next_page = None
        ch_end = (next_page - 1) if next_page else ch_page

        raw_topics = raw_ch.get("topics", [])
        if not isinstance(raw_topics, list):
            raw_topics = []

        topics: list[Topic] = []
        for t_idx, raw_topic in enumerate(raw_topics, start=1):
            if not isinstance(raw_topic, dict):
                continue
            t_title = str(raw_topic.get("title") or f"Topic {t_idx}").strip()
            t_page = int(raw_topic.get("page_start", ch_page))
            next_t_page = None
            if t_idx < len(raw_topics):
                next_t_page = raw_topics[t_idx].get("page_start")
                if isinstance(next_t_page, (int, float)):
                    next_t_page = int(next_t_page)
                else:
                    next_t_page = None
            t_end = (next_t_page - 1) if next_t_page else ch_end

            topics.append(
                Topic(
                    topic_id=f"{chapter_id}_topic_{t_idx:02d}",
                    title=t_title,
                    heading_level=2,
                    page_start=t_page,
                    page_end=t_end,
                    text="",
                )
            )

        if not topics:
            topics.append(
                Topic(
                    topic_id=f"{chapter_id}_topic_01",
                    title=ch_title,
                    heading_level=1,
                    page_start=ch_page,
                    page_end=ch_end,
                    text="",
                )
            )

        chapters.append(
            Chapter(
                chapter_id=chapter_id,
                chapter_number=ch_index,
                title=ch_title,
                page_start=ch_page,
                page_end=ch_end,
                topics=topics,
            )
        )

    return chapters


def _google_api_key() -> str:
    return (
        os.environ.get("VERTEX_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )


def _slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "chapter"
