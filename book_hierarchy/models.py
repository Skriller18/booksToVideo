from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Topic:
    topic_id: str
    title: str
    heading_level: int
    page_start: int
    page_end: int
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chapter:
    chapter_id: str
    chapter_number: int | None
    title: str
    page_start: int
    page_end: int
    topics: list[Topic] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BookHierarchy:
    book_title: str
    source_pdf: str
    extraction_method: str
    extraction_confidence: float
    page_count: int
    chapters: list[Chapter]
    extra: dict[str, Any] = field(default_factory=dict)


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for field_name, field_def in obj.__dataclass_fields__.items():
            value = getattr(obj, field_name)
            if isinstance(value, list):
                value = [to_dict(item) for item in value]
            elif isinstance(value, dict):
                value = {key: to_dict(val) for key, val in value.items()}
            result[field_name] = value
        return result
    if isinstance(obj, list):
        return [to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_dict(val) for key, val in obj.items()}
    return obj
