from __future__ import annotations

import re
from typing import Any

from .models import Chapter, Topic


CHAPTER_KEYWORDS = frozenset({"chapter", "unit", "lesson", "part", "module"})

TOPIC_KEYWORDS = frozenset({
    "reading",
    "comprehension",
    "vocabulary",
    "grammar",
    "writing",
    "speaking",
    "listening",
    "summary",
    "exercise",
    "questions",
    "appreciating",
    "understanding",
    "activity",
    "worksheet",
    "review",
    "assessment",
    "introduction",
    "conclusion",
    "objective",
    "overview",
})

CHAPTER_PATTERNS = [
    re.compile(
        r"^\s*(?:Chapter|Unit|Lesson|Part|Module|CHAPTER|UNIT|LESSON|PART|MODULE)\s+[\dIVXLCDM]+",
    ),
    re.compile(
        r"^\s*(?:Chapter|Unit|Lesson|Part|Module|CHAPTER|UNIT|LESSON|PART|MODULE)\s*[:-]\s",
    ),
]

TOPIC_PATTERNS = [
    re.compile(r"^\s*(?:Section|Topic)\s+[\d]+", re.IGNORECASE),
    re.compile(r"^\s*\d+\.\d+\s"),
    re.compile(
        r"^\s*(?:Reading\s+Comprehension|Vocabulary|Grammar|Writing|Speaking|Listening|"
        r"Appreciating\s+the\s+\w+|Understanding\s+the\s+\w+)",
        re.IGNORECASE,
    ),
]

NARRATIVE_MARKERS = frozenset({
    "she", "he", "they", "we", "you", "her", "his", "their", "our",
    "said", "says", "asked", "replied", "told", "went", "came", "looked",
    "was", "were", "did", "had", "the",
})

FOOTER_SKIP = frozenset({
    "downloaded from",
    "www.",
    "http",
    "copyright",
    "all rights reserved",
    "orient blackswan",
    "page ",
    "\u00a9",
})


def extract_from_headings(
    source_pdf: str,
    doc: Any,
    page_count: int,
) -> tuple[list[Chapter], float]:
    all_headings = _detect_all_headings(doc, page_count)
    chapter_boundaries = _find_chapter_boundaries(all_headings)

    if not chapter_boundaries:
        all_topics = [h for h in all_headings if h["level"] == "topic"]
        if all_topics:
            page_text = _extract_page_text(doc, 0, page_count - 1)
            chapter_boundaries = [
                {
                    "page": 1,
                    "title": "Document",
                    "topic_headings": all_topics,
                }
            ]
        else:
            return [], 0.0

    chapters: list[Chapter] = []

    for ch_index, boundary in enumerate(chapter_boundaries, start=1):
        ch_page = boundary["page"]
        next_ch_page = (
            chapter_boundaries[ch_index]["page"]
            if ch_index < len(chapter_boundaries)
            else page_count + 1
        )
        ch_end_page = max(ch_page, next_ch_page - 1)
        if ch_end_page < ch_page:
            ch_end_page = ch_page

        ch_title = boundary["title"]
        chapter_id = _slug(ch_title) or f"ch_{ch_index:02d}"

        topic_headings = boundary.get("topic_headings", [])
        chapter_topics: list[Topic] = []

        if topic_headings:
            for t_idx, th in enumerate(topic_headings, start=1):
                t_page = th["page"]
                next_t_page = (
                    topic_headings[t_idx]["page"]
                    if t_idx < len(topic_headings)
                    else ch_end_page + 1
                )
                t_end = max(t_page, next_t_page - 1)
                text = _extract_page_text(doc, t_page - 1, t_end - 1)
                chapter_topics.append(
                    Topic(
                        topic_id=f"{chapter_id}_topic_{t_idx:02d}",
                        title=th["title"],
                        heading_level=2 if th["level"] == "topic" else 3,
                        page_start=t_page,
                        page_end=t_end,
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

    if len(chapters) > page_count * 2:
        return [_merge_single_chapter(doc, page_count, chapters, source_pdf)], 0.3

    confidence = min(0.9, 0.3 + (min(len(chapters), 10) * 0.06))
    return chapters, confidence


def _merge_single_chapter(
    doc: Any,
    page_count: int,
    chapters: list[Chapter],
    source_pdf: str,
) -> Chapter:
    all_topics: list[Topic] = []
    for ch in chapters:
        for t in ch.topics:
            all_topics.append(
                Topic(
                    topic_id=t.topic_id,
                    title=t.title,
                    heading_level=t.heading_level,
                    page_start=t.page_start,
                    page_end=t.page_end,
                    text=t.text,
                )
            )

    import re as _re

    stem = _re.sub(r"\.pdf$", "", source_pdf, flags=_re.IGNORECASE)
    title = stem.replace("_", " ").replace("-", " ").title()

    if all_topics:
        all_topics.sort(key=lambda t: t.page_start)
        t_idx = 1
        for topic in all_topics:
            topic.topic_id = f"ch_01_topic_{t_idx:02d}"
            t_idx += 1

    return Chapter(
        chapter_id="ch_01",
        chapter_number=1,
        title=title,
        page_start=1,
        page_end=page_count,
        topics=all_topics,
    )


def _detect_all_headings(doc: Any, page_count: int) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    for i in range(page_count):
        page = doc[i]
        text = page.get_text()
        if not text.strip():
            continue
        lines = text.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line or _is_footer_line(line):
                continue

            if _is_chapter_heading(line):
                headings.append({"page": i + 1, "title": line, "level": "chapter"})
                continue

            if _is_topic_heading(line) and not _is_narrative(line):
                headings.append({"page": i + 1, "title": line, "level": "topic"})

    return headings


def _is_chapter_heading(line: str) -> bool:
    for pattern in CHAPTER_PATTERNS:
        if pattern.match(line):
            return True

    lower = line.lower().strip()
    words = lower.split()
    if not words:
        return False
    if words[0] in CHAPTER_KEYWORDS and len(words) <= 8:
        return True
    return False


def _is_topic_heading(line: str) -> bool:
    for pattern in TOPIC_PATTERNS:
        if pattern.match(line):
            return True

    lower = line.lower().strip()
    if not lower:
        return False
    if _contains_numeric(lower):
        return False

    words = lower.split()
    for word in words:
        if word.strip(".,:;") in TOPIC_KEYWORDS:
            if 2 <= len(words) <= 8:
                return True
    return False


def _is_narrative(line: str) -> bool:
    lower = line.lower()
    words = lower.split()
    if not words:
        return False
    if words[0] in NARRATIVE_MARKERS:
        return True
    if len(words) > 12:
        return True
    story_count = sum(1 for w in words if w in NARRATIVE_MARKERS)
    if story_count >= 3:
        return True
    return False


def _contains_numeric(text: str) -> bool:
    return bool(re.search(r"\b\d+\b", text))


def _is_footer_line(line: str) -> bool:
    lower = line.lower()
    return any(skip in lower for skip in FOOTER_SKIP)


def _find_chapter_boundaries(all_headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chapter_boundaries: list[dict[str, Any]] = []
    for h in all_headings:
        if h["level"] == "chapter":
            chapter_boundaries.append({"page": h["page"], "title": h["title"], "topic_headings": []})

    for i, ch in enumerate(chapter_boundaries):
        start_page = ch["page"]
        end_page = (
            chapter_boundaries[i + 1]["page"] if i + 1 < len(chapter_boundaries) else 999999
        )
        ch["topic_headings"] = [
            h
            for h in all_headings
            if h["level"] == "topic" and start_page <= h["page"] < end_page
        ]

    return chapter_boundaries


def _extract_page_text(doc: Any, start_index: int, end_index: int) -> str:
    parts = []
    max_index = min(end_index, doc.page_count - 1)
    for i in range(max(0, start_index), max_index + 1):
        text = doc[i].get_text().strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "chapter"
