from __future__ import annotations

import json
import os
import re
from typing import Any

from .asset_policy import is_lesson_asset
from .models import Episode, IllustrationRef

SOCIAL_RETENTION_ROLES = ("hook", "setup", "insight", "example", "payoff")


def build_episode_plan(
    chapter: dict[str, Any],
    target_episode_count: int | None,
    clips_per_episode: int,
    clip_duration_seconds: int,
    content_mode: str = "educational",
    short_count: int = 10,
    orchestrator: str = "local",
    orchestrator_model: str = "gemini-2.5-flash",
) -> list[Episode]:
    if content_mode == "social":
        return build_social_short_plan(
            chapter=chapter,
            short_count=short_count,
            clips_per_short=clips_per_episode,
            clip_duration_seconds=clip_duration_seconds,
            orchestrator=orchestrator,
            orchestrator_model=orchestrator_model,
        )

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
                metadata={"content_mode": "educational"},
            )
        )
    return episodes


def build_social_short_plan(
    chapter: dict[str, Any],
    short_count: int,
    clips_per_short: int,
    clip_duration_seconds: int,
    orchestrator: str = "local",
    orchestrator_model: str = "gemini-2.5-flash",
) -> list[Episode]:
    topics = chapter.get("topics", [])
    if not topics:
        raise ValueError("chapter_extraction.json must include at least one topic")
    if short_count <= 0:
        raise ValueError("--short-count must be greater than 0")
    if clips_per_short <= 0:
        raise ValueError("--clips-per-episode must be greater than 0")

    if orchestrator in {"auto", "gemini"} and _has_google_api_key():
        try:
            concepts = _build_llm_social_concepts(
                chapter=chapter,
                short_count=short_count,
                clips_per_short=clips_per_short,
                model=orchestrator_model,
            )
        except Exception:
            if orchestrator == "gemini":
                raise
            concepts = _build_local_social_concepts(chapter, short_count, clips_per_short)
    elif orchestrator == "gemini":
        raise RuntimeError("A Google API key is required for the Gemini social planner")
    else:
        concepts = _build_local_social_concepts(chapter, short_count, clips_per_short)

    duration_seconds = clips_per_short * clip_duration_seconds
    episodes: list[Episode] = []
    for index, concept in enumerate(concepts[:short_count], start=1):
        topic_ids = [
            item
            for item in concept.get("source_topic_ids", [])
            if isinstance(item, str)
        ]
        source_topics = [
            topic
            for topic in topics
            if topic.get("topic_id") in set(topic_ids)
        ] or [topics[min(index - 1, len(topics) - 1)]]
        illustrations = [
            _build_illustration_ref(item)
            for topic in source_topics
            for item in topic.get("illustrations", [])
            if is_lesson_asset(item)
        ]
        source_pages = sorted(
            {
                page
                for topic in source_topics
                for page in topic.get("source_pages", [])
                if isinstance(page, int)
            }
            or {
                page
                for page in concept.get("source_pages", [])
                if isinstance(page, int)
            }
        )
        if not topic_ids:
            topic_ids = [
                str(topic.get("topic_id", f"topic_{index:02d}"))
                for topic in source_topics
            ]

        title = str(concept.get("title") or concept.get("short_title") or f"Viral Short {index}").strip()
        episodes.append(
            Episode(
                episode_id=f"short_{index:02d}",
                title=title,
                duration_seconds=duration_seconds,
                clip_count=clips_per_short,
                learning_goal=str(concept.get("core_insight") or title),
                source_pages=source_pages,
                source_topic_ids=topic_ids,
                illustrations=illustrations,
                micro_drama_arc=list(SOCIAL_RETENTION_ROLES[:clips_per_short]),
                metadata={
                    "content_mode": "social",
                    "short_rank": int(concept.get("rank") or index),
                    "viral_hook": str(concept.get("viral_hook") or title),
                    "core_insight": str(concept.get("core_insight") or title),
                    "share_reason": str(concept.get("share_reason") or "A useful book-grounded insight."),
                    "accuracy_guardrail": str(
                        concept.get("accuracy_guardrail") or "Stay grounded in the parsed book content."
                    ),
                    "social_clips": concept.get("clips", []),
                },
            )
        )
    return episodes


def _build_llm_social_concepts(
    chapter: dict[str, Any],
    short_count: int,
    clips_per_short: int,
    model: str,
) -> list[dict[str, Any]]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is required for the Gemini social planner") from exc

    client = genai.Client(api_key=_google_api_key())
    response = client.models.generate_content(
        model=model,
        contents=_build_social_planner_prompt(chapter, short_count, clips_per_short),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    payload = json.loads(getattr(response, "text", "") or "")
    return _parse_social_concepts(payload, short_count, clips_per_short)


def _build_social_planner_prompt(chapter: dict[str, Any], short_count: int, clips_per_short: int) -> str:
    topics = [
        {
            "topic_id": topic.get("topic_id"),
            "title": topic.get("title"),
            "source_pages": topic.get("source_pages", []),
            "text": topic.get("text", ""),
            "learning_goal": topic.get("learning_goal"),
            "illustrations": [
                {
                    "illustration_id": item.get("illustration_id"),
                    "caption": item.get("caption"),
                    "page_number": item.get("page_number"),
                    "asset_type": item.get("asset_type"),
                    "is_lesson_asset": item.get("is_lesson_asset", True),
                }
                for item in topic.get("illustrations", [])
                if is_lesson_asset(item)
            ],
        }
        for topic in chapter.get("topics", [])
    ]
    return json.dumps(
        {
            "task": (
                "Find the most viral standalone short-video ideas in this parsed book/chapter. "
                "Rank the strongest book-grounded insights and script each for vertical Reels/Shorts "
                "as scene action with off-screen narrator voice-over."
            ),
            "rules": [
                "Return JSON only.",
                f"Create exactly {short_count} shorts.",
                f"Each short must contain exactly {clips_per_short} clips.",
                "Use insight hooks, not fake controversy or generic summaries.",
                "Every claim must be grounded in the provided book text.",
                "Avoid unsupported author/person claims and avoid numbered Step narration.",
                "Write narration as off-screen voice-over, not dialogue or a visible creator talking to camera.",
                "Write visual beats as scenes or metaphors that continue while the narrator speaks.",
                "Optimize for surprise, usefulness, relatability, clarity, and shareability.",
            ],
            "schema": {
                "shorts": [
                    {
                        "rank": 1,
                        "title": "short title",
                        "viral_hook": "curiosity-led opening line",
                        "core_insight": "book-grounded insight",
                        "share_reason": "why viewers would share this",
                        "accuracy_guardrail": "what not to overclaim",
                        "source_topic_ids": ["topic ids"],
                        "source_pages": [1],
                        "clips": [
                            {
                                "retention_role": "hook|setup|insight|example|payoff",
                                "narration": "off-screen narrator voice-over line",
                                "visual_beat": "vertical scene or metaphor action for Veo",
                                "illustration_ids": ["optional illustration ids"],
                                "transition": "opening|match_cut|gentle_cut",
                            }
                        ],
                    }
                ]
            },
            "chapter_title": chapter.get("title"),
            "topics": topics,
        },
        ensure_ascii=True,
    )


def _parse_social_concepts(
    payload: Any,
    short_count: int,
    clips_per_short: int,
) -> list[dict[str, Any]]:
    raw_shorts = payload.get("shorts") if isinstance(payload, dict) else None
    if not isinstance(raw_shorts, list) or len(raw_shorts) != short_count:
        raise ValueError("Social planner response must include exactly the requested short count")
    concepts: list[dict[str, Any]] = []
    for index, raw_short in enumerate(raw_shorts, start=1):
        if not isinstance(raw_short, dict):
            raise ValueError("Social planner shorts must be objects")
        clips = raw_short.get("clips")
        if not isinstance(clips, list) or len(clips) != clips_per_short:
            raise ValueError("Each social short must include exactly the requested clip count")
        title = str(raw_short.get("title") or raw_short.get("short_title") or "").strip()
        hook = str(raw_short.get("viral_hook") or "").strip()
        insight = str(raw_short.get("core_insight") or "").strip()
        if not title or not hook or not insight:
            raise ValueError("Social planner shorts require title, viral_hook, and core_insight")
        concepts.append({**raw_short, "rank": int(raw_short.get("rank") or index)})
    return concepts


def _build_local_social_concepts(
    chapter: dict[str, Any],
    short_count: int,
    clips_per_short: int,
) -> list[dict[str, Any]]:
    candidates = _rank_social_candidates(chapter)
    concepts: list[dict[str, Any]] = []
    for index in range(short_count):
        candidate = candidates[index % len(candidates)]
        title = _social_title(candidate["topic_title"], candidate["fact"])
        hook = f"This idea from {candidate['topic_title']} is more relatable than it first looks."
        insight = candidate["fact"]
        concepts.append(
            {
                "rank": index + 1,
                "title": title,
                "viral_hook": hook,
                "core_insight": insight,
                "share_reason": "It connects a book idea to a familiar real-life pattern.",
                "accuracy_guardrail": "Do not claim more than the source text supports.",
                "source_topic_ids": [candidate["topic_id"]],
                "source_pages": candidate["source_pages"],
                "clips": _build_local_social_clips(
                    topic_title=candidate["topic_title"],
                    fact=insight,
                    hook=hook,
                    clips_per_short=clips_per_short,
                ),
            }
        )
    return concepts


def _rank_social_candidates(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for topic_index, topic in enumerate(chapter.get("topics", []), start=1):
        topic_title = str(topic.get("title") or f"Topic {topic_index}")
        sentences = _extract_sentences(str(topic.get("text") or topic.get("learning_goal") or topic_title))
        for sentence in sentences:
            candidates.append(
                {
                    "score": _social_sentence_score(sentence),
                    "topic_id": str(topic.get("topic_id") or f"topic_{topic_index:02d}"),
                    "topic_title": topic_title,
                    "source_pages": topic.get("source_pages", []),
                    "fact": sentence,
                }
            )
    if not candidates:
        raise ValueError("chapter_extraction.json must include topic text for social planning")
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _extract_sentences(text: str) -> list[str]:
    sentences = [
        " ".join(candidate.split()).strip(" .")
        for candidate in re.split(r"(?<=[.!?])\s+", text.strip())
    ]
    return [sentence for sentence in sentences if len(sentence) > 12] or [" ".join(text.split()).strip(" .")]


def _social_sentence_score(sentence: str) -> int:
    lowered = sentence.lower()
    score = min(len(sentence), 180)
    signal_words = (
        "why",
        "because",
        "but",
        "however",
        "change",
        "problem",
        "mistake",
        "effect",
        "reason",
        "reveals",
        "shows",
        "moves",
        "natural",
        "spreads",
    )
    score += sum(35 for word in signal_words if word in lowered)
    if "?" in sentence:
        score += 40
    return score


def _social_title(topic_title: str, fact: str) -> str:
    cleaned = fact.rstrip(".")
    if len(cleaned) > 72:
        cleaned = cleaned[:69].rstrip() + "..."
    return f"The hidden idea in {topic_title}: {cleaned}"


def _build_local_social_clips(
    topic_title: str,
    fact: str,
    hook: str,
    clips_per_short: int,
) -> list[dict[str, Any]]:
    templates = [
        (
            "hook",
            hook,
            f"Vertical social-video opening: a bold visual metaphor for {topic_title}, fast push-in, immediate curiosity.",
        ),
        (
            "setup",
            f"The book gives us this clue: {fact}.",
            f"Show the book idea as a simple, clear scene about {topic_title}, with one focused action.",
        ),
        (
            "insight",
            f"The interesting part is not just the fact; it is the pattern it reveals.",
            "Turn the scene into a clean visual pattern, using motion to make the insight obvious.",
        ),
        (
            "example",
            f"You can spot the same pattern in everyday life when people react before they fully understand.",
            "Show a relatable modern visual comparison without adding unsupported facts or readable text.",
        ),
        (
            "payoff",
            f"That is the takeaway: {fact}. Follow for more book ideas that explain real life.",
            "End with a satisfying visual payoff and a soft follow cue, no on-screen text required.",
        ),
    ]
    clips: list[dict[str, Any]] = []
    for index, (role, narration, visual_beat) in enumerate(templates[:clips_per_short], start=1):
        clips.append(
            {
                "retention_role": role,
                "narration": narration,
                "visual_beat": visual_beat,
                "illustration_ids": [],
                "transition": "opening" if index == 1 else "match_cut",
            }
        )
    return clips


def _has_google_api_key() -> bool:
    return bool(_google_api_key())


def _google_api_key() -> str:
    return (
        os.environ.get("VERTEX_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )


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
