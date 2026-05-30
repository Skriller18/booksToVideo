from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .asset_policy import lesson_relevance_score
from .models import Episode, IllustrationRef


CHARACTERS = ("Asha", "Kabir")

MICRODRAMA_BEATS = [
    ("cold_open", "A tiny everyday problem visually introduces the topic."),
    ("curious_question", "The scene poses the core question through action, not dialogue."),
    ("scene_reveal", "The narration reveals the core idea in one clear visual moment."),
    ("guided_observation", "The scene highlights the first important clue for students."),
    ("concept_turn", "The visual action shows why that clue matters."),
    ("meaningful_illustration", "A textbook illustration appears only if it clarifies the idea."),
    ("cause_and_effect", "A single action makes the relationship visible."),
    ("misread", "A plausible wrong idea appears briefly."),
    ("correction", "The scene corrects the misunderstanding through action."),
    ("practice_moment", "The idea appears in a familiar situation."),
    ("emotional_payoff", "The silent characters react as the idea becomes clear."),
    ("recap", "The episode restates the learning through narrator-led visuals."),
    ("bridge", "A final moment creates curiosity for the next episode."),
]

ILLUSTRATION_BEAT_KEYS = {"meaningful_illustration", "guided_observation", "recap"}


@dataclass(frozen=True)
class OrchestratedClip:
    arc_key: str
    visual_beat: str
    narration: str
    reference_illustrations: list[IllustrationRef]
    transition: str
    metadata: dict[str, Any]


def build_orchestrated_episode_clips(
    chapter: dict[str, Any],
    episode: Episode,
    clip_count: int,
    orchestrator: str = "local",
    orchestrator_model: str = "gemini-3.1-pro-preview",
) -> list[OrchestratedClip]:
    """Create LLM-orchestrator style beats with a deterministic local fallback.

    This is the layer that decides the episode flow, spoken script, and whether
    an illustration is meaningful enough to send to Veo as a reference image.
    A live LLM can replace this function later without changing downstream
    manifests because the contract is already explicit at the clip-beat level.
    """

    if episode.metadata.get("content_mode") == "social":
        return _build_social_episode_clips(episode, clip_count)

    if orchestrator in {"auto", "gemini"} and _has_google_api_key():
        try:
            return _build_llm_episode_clips(
                chapter=chapter,
                episode=episode,
                clip_count=clip_count,
                model=orchestrator_model,
            )
        except Exception:
            if orchestrator == "gemini":
                raise

    topic_text = _topic_text_for_episode(chapter, episode)
    facts = _extract_fact_units(topic_text, episode.learning_goal)
    beats = _episode_beat_sequence(clip_count)
    selected_illustration = _select_meaningful_illustration(episode, facts)
    clips: list[OrchestratedClip] = []

    for index, (arc_key, arc_description) in enumerate(beats, start=1):
        fact = facts[min(index - 1, len(facts) - 1)] if facts else episode.learning_goal
        next_fact = facts[min(index, len(facts) - 1)] if facts else episode.learning_goal
        use_illustration = _should_use_illustration(arc_key, selected_illustration)
        references = [selected_illustration] if use_illustration and selected_illustration else []
        narration = _build_microdrama_narration(
            episode=episode,
            arc_key=arc_key,
            fact=fact,
            next_fact=next_fact,
            is_first=index == 1,
            is_last=index == clip_count,
        )
        visual_beat = _build_microdrama_visual(
            episode=episode,
            arc_key=arc_key,
            arc_description=arc_description,
            fact=fact,
            illustration=selected_illustration if use_illustration else None,
        )
        clips.append(
            OrchestratedClip(
                arc_key=arc_key,
                visual_beat=visual_beat,
                narration=narration,
                reference_illustrations=references,
                transition="match_cut" if index > 1 else "opening",
                metadata={
                    "orchestrator": "deterministic_microdrama",
                    "illustration_policy": "meaningful_only" if references else "no_reference_image",
                    "story_position": index,
                },
            )
        )

    return clips


def _build_social_episode_clips(episode: Episode, clip_count: int) -> list[OrchestratedClip]:
    raw_clips = episode.metadata.get("social_clips", [])
    if not isinstance(raw_clips, list):
        raw_clips = []
    raw_clips = raw_clips[:clip_count]
    if len(raw_clips) < clip_count:
        raw_clips = [
            *raw_clips,
            *_fallback_social_clip_specs(episode, clip_count - len(raw_clips)),
        ]

    illustrations_by_id = {
        item.illustration_id: item
        for item in episode.illustrations
        if _illustration_candidate_score(item, episode, [episode.learning_goal]) >= 0
    }
    clips: list[OrchestratedClip] = []
    for index, raw_clip in enumerate(raw_clips, start=1):
        if not isinstance(raw_clip, dict):
            raw_clip = {}
        retention_role = str(raw_clip.get("retention_role") or f"beat_{index}").strip()
        narration = _strip_numbered_prefix(str(raw_clip.get("narration") or "").strip())
        visual_beat = str(raw_clip.get("visual_beat") or "").strip()
        if not narration:
            narration = _fallback_social_narration(episode, retention_role, index)
        if not visual_beat:
            visual_beat = _fallback_social_visual(episode, retention_role)

        illustration_ids = raw_clip.get("illustration_ids") or []
        if not isinstance(illustration_ids, list):
            illustration_ids = []
        references = [
            illustrations_by_id[item]
            for item in illustration_ids
            if isinstance(item, str) and item in illustrations_by_id
        ][:1]
        clips.append(
            OrchestratedClip(
                arc_key=retention_role,
                visual_beat=visual_beat,
                narration=narration,
                reference_illustrations=references,
                transition=str(raw_clip.get("transition") or ("opening" if index == 1 else "match_cut")),
                metadata={
                    "orchestrator": "social_planner",
                    "content_mode": "social",
                    "short_rank": episode.metadata.get("short_rank"),
                    "viral_hook": episode.metadata.get("viral_hook"),
                    "core_insight": episode.metadata.get("core_insight"),
                    "retention_role": retention_role,
                    "share_reason": episode.metadata.get("share_reason"),
                    "accuracy_guardrail": episode.metadata.get("accuracy_guardrail"),
                    "illustration_policy": "meaningful_only" if references else "no_reference_image",
                    "story_position": index,
                },
            )
        )
    return clips


def _fallback_social_clip_specs(episode: Episode, count: int) -> list[dict[str, str]]:
    roles = ("hook", "setup", "insight", "example", "payoff")
    return [
        {
            "retention_role": roles[index % len(roles)],
            "narration": _fallback_social_narration(episode, roles[index % len(roles)], index + 1),
            "visual_beat": _fallback_social_visual(episode, roles[index % len(roles)]),
            "transition": "match_cut",
        }
        for index in range(count)
    ]


def _fallback_social_narration(episode: Episode, retention_role: str, index: int) -> str:
    if retention_role == "hook" or index == 1:
        return str(episode.metadata.get("viral_hook") or f"This book idea about {episode.title} is worth a second look.")
    if retention_role == "payoff":
        return f"The takeaway is simple: {episode.learning_goal}"
    return f"The book-grounded insight is this: {episode.learning_goal}"


def _fallback_social_visual(episode: Episode, retention_role: str) -> str:
    return (
        f"Vertical social-video {retention_role} beat for {episode.title}: bold simple motion, "
        "one clear metaphor, high-retention pacing, no readable text."
    )


def _build_llm_episode_clips(
    chapter: dict[str, Any],
    episode: Episode,
    clip_count: int,
    model: str,
) -> list[OrchestratedClip]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is required for the Gemini orchestrator") from exc

    client = genai.Client(api_key=_google_api_key())
    prompt = _build_llm_prompt(chapter, episode, clip_count)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw_text = getattr(response, "text", "") or ""
    payload = json.loads(raw_text)
    return _parse_llm_payload(payload, episode, clip_count)


def _build_llm_prompt(chapter: dict[str, Any], episode: Episode, clip_count: int) -> str:
    illustrations = [
        {
            "illustration_id": item.illustration_id,
            "caption": item.caption,
            "page_number": item.page_number,
            "asset_type": item.asset_type,
            "is_lesson_asset": item.is_lesson_asset,
        }
        for item in episode.illustrations
        if _illustration_candidate_score(item, episode, []) >= 0
    ]
    topic_text = _topic_text_for_episode(chapter, episode)
    return json.dumps(
        {
            "task": (
                "Create a narration-first educational micro-drama episode script for children. "
                "Choose clips, flow, narration, and visual beats so each scene action matches the narrator's "
                "meaning. Use textbook illustrations only when they clarify meaning; otherwise leave "
                "illustration_ids empty so Veo is not confused."
            ),
            "rules": [
                "Return JSON only.",
                "Create exactly the requested number of clips.",
                "Do not write Step 1, Step 2, or numbered narration.",
                "Keep one continuous teaching scene flow with silent characters only as visual actors.",
                "Each narration line must be off-screen explanatory voice-over, not character dialogue, teacher dialogue, or a visible presenter.",
                "Visual beats must show the narration meaning through action, diagrams, objects, board work, experiments, or meaningful textbook illustrations.",
                "Do not stage a visible speaker delivering the narration, lip-syncing, or gesturing like a presenter.",
                "Use illustration_ids only for clips where the illustration is meaningful.",
            ],
            "schema": {
                "clips": [
                    {
                        "arc_key": "short_snake_case",
                        "visual_beat": "video action for Veo",
                        "narration": "off-screen narrator voice-over line",
                        "illustration_ids": ["optional illustration ids"],
                        "transition": "opening|match_cut|gentle_cut",
                    }
                ]
            },
            "chapter_title": chapter.get("title"),
            "episode": {
                "episode_id": episode.episode_id,
                "title": episode.title,
                "learning_goal": episode.learning_goal,
                "clip_count": clip_count,
                "source_pages": episode.source_pages,
            },
            "topic_text": topic_text,
            "available_illustrations": illustrations,
        },
        ensure_ascii=True,
    )


def _parse_llm_payload(
    payload: Any,
    episode: Episode,
    clip_count: int,
) -> list[OrchestratedClip]:
    raw_clips = payload.get("clips") if isinstance(payload, dict) else None
    if not isinstance(raw_clips, list) or len(raw_clips) != clip_count:
        raise ValueError("LLM orchestrator response must include exactly the requested clip count")

    illustrations_by_id = {
        item.illustration_id: item
        for item in episode.illustrations
        if _illustration_candidate_score(item, episode, []) >= 0
    }
    clips: list[OrchestratedClip] = []
    for index, raw_clip in enumerate(raw_clips, start=1):
        if not isinstance(raw_clip, dict):
            raise ValueError("LLM orchestrator clips must be objects")
        narration = _strip_numbered_prefix(str(raw_clip.get("narration", "")).strip())
        visual_beat = str(raw_clip.get("visual_beat", "")).strip()
        if not narration or not visual_beat:
            raise ValueError("LLM orchestrator clips require narration and visual_beat")

        illustration_ids = raw_clip.get("illustration_ids") or []
        if not isinstance(illustration_ids, list):
            illustration_ids = []
        references = [
            illustrations_by_id[item]
            for item in illustration_ids
            if isinstance(item, str) and item in illustrations_by_id
        ][:1]
        clips.append(
            OrchestratedClip(
                arc_key=str(raw_clip.get("arc_key") or f"clip_{index:02d}"),
                visual_beat=visual_beat,
                narration=narration,
                reference_illustrations=references,
                transition=str(raw_clip.get("transition") or ("opening" if index == 1 else "match_cut")),
                metadata={
                    "orchestrator": "gemini",
                    "illustration_policy": "meaningful_only" if references else "no_reference_image",
                    "story_position": index,
                },
            )
        )
    return clips


def _strip_numbered_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:step\s*)?\d+[\).:-]\s*", "", text, flags=re.IGNORECASE)


def _has_google_api_key() -> bool:
    return bool(_google_api_key())


def _google_api_key() -> str:
    return (
        os.environ.get("VERTEX_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )


def _topic_text_for_episode(chapter: dict[str, Any], episode: Episode) -> str:
    topic_ids = set(episode.source_topic_ids)
    parts = [
        topic.get("text", "")
        for topic in chapter.get("topics", [])
        if topic.get("topic_id") in topic_ids
    ]
    return " ".join(part.strip() for part in parts if part.strip())


def _extract_fact_units(topic_text: str, fallback: str) -> list[str]:
    candidates = re.split(r"(?<=[.!?])\s+", topic_text.strip())
    facts = [_clean_fact(candidate) for candidate in candidates if _clean_fact(candidate)]
    if facts:
        return facts
    return [_clean_fact(fallback)]


def _clean_fact(text: str) -> str:
    return " ".join(text.split()).strip(" .")


def _episode_beat_sequence(clip_count: int) -> list[tuple[str, str]]:
    if clip_count <= len(MICRODRAMA_BEATS):
        return MICRODRAMA_BEATS[:clip_count]

    extra_count = clip_count - len(MICRODRAMA_BEATS)
    middle_insert_at = len(MICRODRAMA_BEATS) - 2
    extra_beats = [
        (
            f"development_{index:02d}",
            "The story deepens the same idea with a new connected example.",
        )
        for index in range(1, extra_count + 1)
    ]
    return MICRODRAMA_BEATS[:middle_insert_at] + extra_beats + MICRODRAMA_BEATS[middle_insert_at:]


def _select_meaningful_illustration(
    episode: Episode,
    facts: list[str],
) -> IllustrationRef | None:
    if not episode.illustrations:
        return None

    ranked: list[tuple[int, IllustrationRef]] = []
    for illustration in episode.illustrations:
        score = _illustration_candidate_score(illustration, episode, facts)
        if score >= 0:
            ranked.append((score, illustration))

    if not ranked:
        return None

    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_illustration = ranked[0]
    if best_score > 0:
        return best_illustration
    return None


def _illustration_candidate_score(
    illustration: IllustrationRef,
    episode: Episode,
    facts: list[str],
) -> int:
    raw = {
        "illustration_id": illustration.illustration_id,
        "path": illustration.path,
        "caption": illustration.caption,
        "source_filename": illustration.source_filename,
        "asset_type": illustration.asset_type,
        "is_lesson_asset": illustration.is_lesson_asset,
        "rejection_reason": illustration.rejection_reason,
    }
    lesson_text = " ".join([episode.title, episode.learning_goal, *facts])
    return lesson_relevance_score(raw, lesson_text)


def _should_use_illustration(
    arc_key: str,
    illustration: IllustrationRef | None,
) -> bool:
    return bool(illustration and arc_key in ILLUSTRATION_BEAT_KEYS)


def _build_microdrama_narration(
    episode: Episode,
    arc_key: str,
    fact: str,
    next_fact: str,
    is_first: bool,
    is_last: bool,
) -> str:
    if is_first:
        return f"We begin with a small visual clue that makes {episode.title} worth looking at closely."
    if arc_key == "curious_question":
        return f"At first the scene looks simple, but the important question comes from this clue: {fact}."
    if arc_key == "scene_reveal":
        return f"As the action slows down, the big idea becomes clear: {fact}."
    if arc_key == "guided_observation":
        return "The first clue stands out, and the visuals connect it to what students already know."
    if arc_key == "concept_turn":
        return f"That clue changes how we understand the scene, because {next_fact}."
    if arc_key == "meaningful_illustration":
        return f"Now the picture from the book helps us see the idea clearly: {fact}."
    if arc_key == "cause_and_effect":
        return f"When the class changes one thing, the result shows the relationship clearly."
    if arc_key == "misread":
        return "For a moment, the visuals show a likely wrong idea, which is exactly where many students get confused."
    if arc_key == "correction":
        return f"The scene changes the guess into the right idea: {fact}."
    if arc_key == "practice_moment":
        return f"The same idea appears in a familiar example, and it still works: {next_fact}."
    if arc_key == "emotional_payoff":
        return f"That is when the small moment makes the bigger concept clear."
    if arc_key == "recap" or is_last:
        return f"So this episode teaches one connected idea: {episode.learning_goal}"
    if arc_key == "bridge":
        return "The answer is clear now, but it opens the next question in the chapter."
    return f"As the moment continues, the important idea becomes visible: {fact}."


def _build_microdrama_visual(
    episode: Episode,
    arc_key: str,
    arc_description: str,
    fact: str,
    illustration: IllustrationRef | None,
) -> str:
    if illustration:
        caption = _clean_fact(illustration.caption or episode.title)
        return (
            f"{arc_description} The scene uses only the relevant textbook illustration, "
            f"focused on: {caption}. Use a pointer, highlight motion, or silent character action to draw attention "
            "to one meaningful detail without dialogue."
        )

    if arc_key == "misread":
        return (
            f"{arc_description} Show a brief visual misunderstanding about {episode.title}, "
            "then hold the moment before it is corrected."
        )
    if arc_key == "correction":
        return (
            f"{arc_description} Correct the previous misunderstanding with one clear action "
            f"that shows: {fact}."
        )
    if arc_key == "bridge":
        return (
            f"{arc_description} Keep the same classroom scene and end on a curious look toward "
            "the next connected idea."
        )
    return (
        f"{arc_description} Continue the same narration-led classroom scene and match the visuals to the voice-over. "
        f"Show {episode.title} through simple student-friendly motion: {fact}."
    )
