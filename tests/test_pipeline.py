import json
import tempfile
import unittest
from pathlib import Path

from book_to_video.datalab_extractor import normalize_datalab_convert_result
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

    def test_datalab_result_normalizes_to_chapter_extraction(self) -> None:
        datalab_result = _load_json("examples/datalab_convert.sample.json")
        with tempfile.TemporaryDirectory() as tmp:
            chapter = normalize_datalab_convert_result(
                datalab_result=datalab_result,
                source_pdf="light-and-shadows.pdf",
                output_dir=Path(tmp),
            )

            self.assertEqual(chapter["provider"], "datalab")
            self.assertEqual(chapter["title"], "Light and Shadows")
            self.assertEqual(len(chapter["pages"]), 2)
            self.assertEqual(len(chapter["topics"]), 2)
            self.assertEqual(chapter["topics"][0]["illustrations"][0]["illustration_id"], "illustration_001")
            self.assertTrue(Path(chapter["topics"][0]["illustrations"][0]["path"]).exists())


def _load_sample() -> dict:
    return _load_json("examples/chapter_extraction.sample.json")


def _load_json(relative_path: str) -> dict:
    with (ROOT / relative_path).open("r", encoding="utf-8") as file:
        return json.load(file)


if __name__ == "__main__":
    unittest.main()
