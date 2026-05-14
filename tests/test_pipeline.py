import json
import unittest
from pathlib import Path

from book_to_video.pipeline import build_planning_artifacts


ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def test_default_episode_count_matches_topics(self) -> None:
        chapter = _load_sample()
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=None,
            clips_per_episode=15,
            clip_duration_seconds=8,
        )

        self.assertEqual(artifacts["episode_plan"]["episode_count"], 3)
        self.assertEqual(artifacts["storyboard"]["clip_count"], 45)
        self.assertEqual(artifacts["veo_manifest"]["clip_job_count"], 45)
        self.assertEqual(artifacts["stitch_manifest"]["episode_count"], 3)

    def test_target_episode_count_expands_to_300_clips(self) -> None:
        chapter = _load_sample()
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=20,
            clips_per_episode=15,
            clip_duration_seconds=8,
        )

        self.assertEqual(artifacts["episode_plan"]["episode_count"], 20)
        self.assertEqual(artifacts["storyboard"]["clip_count"], 300)
        self.assertEqual(artifacts["veo_manifest"]["clip_job_count"], 300)
        self.assertEqual(artifacts["stitch_manifest"]["episode_count"], 20)
        self.assertEqual(
            len(artifacts["stitch_manifest"]["episodes"][0]["clip_paths"]),
            15,
        )


def _load_sample() -> dict:
    with (ROOT / "examples" / "chapter_extraction.sample.json").open("r", encoding="utf-8") as file:
        return json.load(file)


if __name__ == "__main__":
    unittest.main()

