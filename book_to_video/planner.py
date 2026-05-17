from __future__ import annotations

from typing import Any

from .asset_policy import is_lesson_asset
from .models import Episode, IllustrationRef


def build_episode_plan(
    chapter: dict[str, Any],
    target_episode_count: int | None,
    clips_per_episode: int,
    clip_duration_seconds: int,
) -> list[Episode]:
    topics = chapter.get("topics", [])
    if not topics:
        raise ValueError("chapter_extraction.json must include at least one topic")

    episode_units = _build_episode_units(topics, target_episode_count)
    duration_seconds = clips_per_episode * clip_duration_seconds
    episodes: list[Episode] = []

    for index, topic in enumerate(episode_units, start=1):
        illustrations = [
            _build_illustration_ref(item)
            for item in topic.get("illustrations", [])
            if is_lesson_asset(item)
        ]
        source_pages = sorted(set(topic.get("source_pages", [])))
        source_topic_id = topic.get("topic_id", f"topic_{index:02d}")
        episodes.append(
            Episode(
                episode_id=f"episode_{index:02d}",
                title=topic.get("episode_title") or topic.get("title", f"Topic {index}"),
                duration_seconds=duration_seconds,
                clip_count=clips_per_episode,
                learning_goal=topic.get("learning_goal") or _default_learning_goal(topic),
                source_pages=source_pages,
                source_topic_ids=[source_topic_id],
                illustrations=illustrations,
                micro_drama_arc=[
                    "Open on a relatable classroom problem",
                    "Let the learners ask the core question",
                    "Reveal only the illustration that clarifies the idea",
                    "Teach through connected action, not numbered steps",
                    "Correct one likely misunderstanding",
                    "End with a story beat that bridges forward",
                ],
            )
        )
    return episodes


def _build_episode_units(
    topics: list[dict[str, Any]],
    target_episode_count: int | None,
) -> list[dict[str, Any]]:
    if target_episode_count is None:
        return topics
    if target_episode_count <= 0:
        raise ValueError("--episode-count must be greater than 0")
    if target_episode_count <= len(topics):
        return topics[:target_episode_count]

    allocations = _allocate_episode_counts(topics, target_episode_count)
    episode_units: list[dict[str, Any]] = []
    for topic, count in zip(topics, allocations):
        for part_index in range(1, count + 1):
            unit = dict(topic)
            if count > 1:
                unit["episode_title"] = f"{topic.get('title', 'Topic')} - Part {part_index}"
                unit["learning_goal"] = _part_learning_goal(topic, part_index, count)
            episode_units.append(unit)
    return episode_units


def _allocate_episode_counts(topics: list[dict[str, Any]], target_episode_count: int) -> list[int]:
    allocations = [1 for _ in topics]
    remaining = target_episode_count - len(topics)
    ranked_indices = sorted(
        range(len(topics)),
        key=lambda index: len(topics[index].get("text", "")),
        reverse=True,
    )
    cursor = 0
    while remaining > 0:
        allocations[ranked_indices[cursor % len(ranked_indices)]] += 1
        remaining -= 1
        cursor += 1
    return allocations


def _part_learning_goal(topic: dict[str, Any], part_index: int, part_count: int) -> str:
    base_goal = topic.get("learning_goal") or _default_learning_goal(topic)
    return f"{base_goal} This is part {part_index} of {part_count}, so keep the explanation focused and progressive."


def _build_illustration_ref(raw: dict[str, Any]) -> IllustrationRef:
    return IllustrationRef(
        illustration_id=raw.get("illustration_id", "illustration_unknown"),
        path=raw.get("path", ""),
        caption=raw.get("caption", ""),
        page_number=raw.get("page_number"),
        source_filename=raw.get("source_filename", ""),
        asset_type=raw.get("asset_type", "candidate_lesson_illustration"),
        is_lesson_asset=bool(raw.get("is_lesson_asset", True)),
        rejection_reason=raw.get("rejection_reason", ""),
    )


def _default_learning_goal(topic: dict[str, Any]) -> str:
    title = topic.get("title", "this topic")
    return f"Students understand the main idea of {title} and can explain it in their own words."
