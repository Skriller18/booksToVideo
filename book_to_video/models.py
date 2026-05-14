from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class IllustrationRef:
    illustration_id: str
    path: str
    caption: str = ""
    page_number: int | None = None


@dataclass(frozen=True)
class Episode:
    episode_id: str
    title: str
    duration_seconds: int
    clip_count: int
    learning_goal: str
    source_pages: list[int]
    source_topic_ids: list[str]
    illustrations: list[IllustrationRef]
    micro_drama_arc: list[str]


@dataclass(frozen=True)
class ClipBeat:
    chapter_id: str
    episode_id: str
    global_clip_index: int
    episode_clip_index: int
    duration_seconds: int
    source_pages: list[int]
    reference_illustrations: list[IllustrationRef]
    narration: str
    visual_beat: str
    veo_prompt: str
    negative_prompt: str
    transition: str = "cut"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StitchEpisode:
    episode_id: str
    title: str
    output_video: str
    clip_paths: list[str]
    duration_seconds: int

