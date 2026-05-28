from __future__ import annotations

import re
from typing import Any

from .models import Chapter, Topic


def extract_from_toc(
    source_pdf: str,
    toc: list[tuple[int, str, int]],
    page_count: int,
    doc: Any,
) -> tuple[list[Chapter], float]:
    chapters: list[Chapter] = []
    confidence = 0.0

    toc_entries = [(level, title.strip(), page_num) for level, title, page_num in toc]
    chapter_entries = []
    topic_entries = []

    for level, title, page_num in toc_entries:
        title = _clean_title(title)
        if not title:
            continue
        if level == 1:
            chapter_entries.append((title, page_num))
        else:
            topic_entries.append((level, title, page_num))

    if not chapter_entries and not topic_entries:
        return chapters, 0.0

    if not chapter_entries and topic_entries:
        grouped: dict[str, list[tuple[int, str, int]]] = {}
        for level, title, page_num in topic_entries:
            key = f"Section_{page_num}"
            grouped.setdefault(key, []).append((level, title, page_num))
        chapter_entries = [(key, min(entries[0][2] for entries in grouped.values()))]
        topic_entries = topic_entries

    for ch_index, (ch_title, ch_page) in enumerate(chapter_entries, start=1):
        chapter_id = _slug(ch_title) or f"ch_{ch_index:02d}"

        next_chapter_page = None
        if ch_index < len(chapter_entries):
            next_chapter_page = chapter_entries[ch_index][1]
        ch_end_page = (next_chapter_page - 1) if next_chapter_page else page_count

        chapter_topics: list[Topic] = []
        ch_topics = [
            (level, title, page_num)
            for level, title, page_num in topic_entries
            if page_num >= ch_page and (next_chapter_page is None or page_num < next_chapter_page)
        ]

        for t_idx, (t_level, t_title, t_page) in enumerate(ch_topics, start=1):
            next_topic_page = None
            if t_idx < len(ch_topics):
                next_topic_page = ch_topics[t_idx][2]
            t_end_page = (next_topic_page - 1) if next_topic_page else ch_end_page

            text = _extract_page_text(doc, t_page - 1, t_end_page - 1)

            chapter_topics.append(
                Topic(
                    topic_id=f"{chapter_id}_topic_{t_idx:02d}",
                    title=t_title,
                    heading_level=t_level,
                    page_start=t_page,
                    page_end=t_end_page,
                    text=text,
                )
            )

        if not chapter_topics:
            text = _extract_page_text(doc, ch_page - 1, ch_end_page - 1)
            chapter_topics.append(
                Topic(
                    topic_id=f"{chapter_id}_topic_01",
                    title=ch_title,
                    heading_level=1,
                    page_start=ch_page,
                    page_end=ch_end_page,
                    text=text,
                )
            )

        chapters.append(
            Chapter(
                chapter_id=chapter_id,
                chapter_number=ch_index,
                title=ch_title,
                page_start=ch_page,
                page_end=ch_end_page,
                topics=chapter_topics,
            )
        )

    confidence = 1.0 if len(chapters) >= 1 else 0.7
    return chapters, confidence


def _extract_page_text(doc: Any, start_index: int, end_index: int) -> str:
    parts = []
    max_index = min(end_index, doc.page_count - 1)
    for i in range(max(0, start_index), max_index + 1):
        text = doc[i].get_text().strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^[\d]+[\.\)]\s*", "", title)
    title = title.strip(" -")
    return title


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "chapter"
