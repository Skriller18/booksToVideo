from __future__ import annotations

from typing import Any

from .models import ClipBeat, Episode
from .prompts import NEGATIVE_PROMPT, build_veo_prompt


ARC_TEMPLATES = [
    ("hook", "A curious everyday moment raises the main question."),
    ("question", "The learner notices the textbook illustration and wonders what is happening."),
    ("setup", "The key objects from the textbook page appear clearly on screen."),
    ("observe", "The first important detail in the illustration comes alive."),
    ("explain", "The narrator explains the idea with a simple classroom example."),
    ("zoom", "The camera focuses on the most important part of the diagram or scene."),
    ("compare", "Two simple states are compared side by side through motion."),
    ("cause_effect", "The cause and effect relationship is shown through a single action."),
    ("mistake", "A common student misconception appears visually, then is corrected."),
    ("practice", "The learner applies the idea to a familiar Indian classroom or home example."),
    ("reinforce", "The textbook illustration returns with the concept clearer than before."),
    ("recap_1", "The first half of the concept is summarized visually."),
    ("recap_2", "The second half of the concept is summarized visually."),
    ("check", "The learner answers the original question with confidence."),
    ("bridge", "The final shot connects this idea to the next topic in the chapter."),
]


def build_clip_beats(
    chapter: dict[str, Any],
    episodes: list[Episode],
    clip_duration_seconds: int,
) -> list[ClipBeat]:
    clips: list[ClipBeat] = []
    global_index = 1

    for episode in episodes:
        topic_text = _topic_text_for_episode(chapter, episode)
        for episode_clip_index in range(1, episode.clip_count + 1):
            arc_key, arc_description = ARC_TEMPLATES[(episode_clip_index - 1) % len(ARC_TEMPLATES)]
            narration = _build_narration(episode, topic_text, arc_key, episode_clip_index)
            visual_beat = _build_visual_beat(episode, arc_description)
            clip = ClipBeat(
                chapter_id=chapter["chapter_id"],
                episode_id=episode.episode_id,
                global_clip_index=global_index,
                episode_clip_index=episode_clip_index,
                duration_seconds=clip_duration_seconds,
                source_pages=episode.source_pages,
                reference_illustrations=episode.illustrations[:3],
                narration=narration,
                visual_beat=visual_beat,
                veo_prompt="",
                negative_prompt=NEGATIVE_PROMPT,
                transition="cut",
                metadata={"arc_key": arc_key},
            )
            clips.append(
                ClipBeat(
                    **{
                        **clip.__dict__,
                        "veo_prompt": build_veo_prompt(clip),
                    }
                )
            )
            global_index += 1

    return clips


def _topic_text_for_episode(chapter: dict[str, Any], episode: Episode) -> str:
    topics = chapter.get("topics", [])
    topic_ids = set(episode.source_topic_ids)
    parts = [topic.get("text", "") for topic in topics if topic.get("topic_id") in topic_ids]
    return " ".join(part.strip() for part in parts if part.strip())


def _build_narration(episode: Episode, topic_text: str, arc_key: str, clip_index: int) -> str:
    short_topic = _shorten(topic_text, 140)
    if arc_key == "hook":
        return f"Have you ever noticed this in real life? Today we are exploring {episode.title}."
    if arc_key == "question":
        return f"Look carefully at the picture from your book. What is it trying to show us about {episode.title}?"
    if arc_key.startswith("recap"):
        return f"So the main idea is simple: {episode.learning_goal}"
    if arc_key == "bridge":
        return "Keep this idea in mind, because the next part of the chapter builds on it."
    if short_topic:
        return f"Step {clip_index}: {short_topic}"
    return f"Step {clip_index}: {episode.learning_goal}"


def _build_visual_beat(episode: Episode, arc_description: str) -> str:
    if episode.illustrations:
        caption = episode.illustrations[0].caption
        if caption:
            return f"{arc_description} The scene uses the textbook figure: {caption}"
    return f"{arc_description} The scene explains {episode.title} with simple objects and student-friendly motion"


def _shorten(text: str, max_length: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."

