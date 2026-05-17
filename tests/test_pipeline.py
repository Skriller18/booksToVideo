import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from book_to_video.cli import load_env_file
from book_to_video.datalab_extractor import normalize_datalab_convert_result
from book_to_video.pipeline import build_planning_artifacts
from book_to_video.stitcher import stitch_from_manifest
from book_to_video.veo_client import VeoGenerationOptions, generate_veo_clips_from_manifest


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
        first_job = artifacts["veo_manifest"]["jobs"][0]
        self.assertEqual(first_job["audio"]["mode"], "native")
        self.assertIn("Indian English teacher voice", first_job["audio"]["voice_profile"])
        self.assertIn("Native audio", first_job["prompt"])

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

    def test_stitch_manifest_dry_run_reports_expected_outputs(self) -> None:
        chapter = _load_sample()
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=2,
            clips_per_episode=15,
            clip_duration_seconds=8,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = stitch_from_manifest(
                stitch_manifest=artifacts["stitch_manifest"],
                media_root=Path(tmp),
                output_root=Path(tmp),
                dry_run=True,
            )

            self.assertTrue(result["dry_run"])
            self.assertEqual(len(result["episode_results"]), 2)
            self.assertEqual(result["episode_results"][0]["clip_count"], 15)
            self.assertEqual(result["episode_results"][0]["missing_clip_count"], 15)
            self.assertEqual(result["chapter_result"]["episode_count"], 2)

    def test_veo_generation_updates_manifest_and_writes_clip(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "A simple educational animation.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "pending",
                }
            ]
        }
        persisted_statuses = []

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=Path(tmp),
                options=VeoGenerationOptions(poll_interval_seconds=0, max_polls=1, continuity_enabled=False),
                persist_manifest=lambda payload: persisted_statuses.append(payload["jobs"][0]["status"]),
                client=FakeVeoClient(),
            )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertEqual(manifest["jobs"][0]["status"], "completed")
            self.assertTrue((Path(tmp) / "clips/clip_0001.mp4").exists())
            self.assertIn("running", persisted_statuses)
            self.assertIn("completed", persisted_statuses)

    def test_veo_generation_skips_existing_completed_clip(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "A simple educational animation.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "completed",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "clips/clip_0001.mp4"
            output_path.parent.mkdir(parents=True)
            output_path.write_bytes(b"existing-video")

            fake_client = FakeVeoClient()
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=Path(tmp),
                options=VeoGenerationOptions(poll_interval_seconds=0, max_polls=1, continuity_enabled=False),
                client=fake_client,
            )

            self.assertEqual(result["generated_clip_count"], 0)
            self.assertEqual(result["skipped_clip_count"], 1)
            self.assertEqual(fake_client.submitted_count, 0)

    def test_veo_generation_uses_previous_last_frame_for_continuity(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "episode_id": "episode_01",
                    "duration_seconds": 8,
                    "prompt": "Opening animation.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "completed",
                    "continuity": {
                        "last_frame_path": "continuity/veo_0001_last_frame.png",
                    },
                },
                {
                    "job_id": "veo_0002",
                    "episode_id": "episode_01",
                    "duration_seconds": 8,
                    "prompt": "Continue the same animation.",
                    "output_path": "clips/clip_0002.mp4",
                    "status": "pending",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip_path = root / "clips/clip_0001.mp4"
            clip_path.parent.mkdir(parents=True)
            clip_path.write_bytes(b"existing-video")
            last_frame_path = root / "continuity/veo_0001_last_frame.png"
            last_frame_path.parent.mkdir(parents=True)
            last_frame_path.write_bytes(b"fake-frame")

            fake_client = FakeVeoClient()
            with mock.patch("book_to_video.veo_client._extract_last_frame") as extract_last_frame:
                extract_last_frame.side_effect = lambda _video, frame, _options: frame.write_bytes(b"fake-frame")
                result = generate_veo_clips_from_manifest(
                    veo_manifest=manifest,
                    media_root=root,
                    options=VeoGenerationOptions(poll_interval_seconds=0, max_polls=1),
                    client=fake_client,
                )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertEqual(fake_client.start_frames, [last_frame_path])
            self.assertEqual(manifest["jobs"][1]["continuity"]["start_frame_path"], str(last_frame_path))

    def test_env_file_loader_reads_keys_without_overriding_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "DATALAB_API_KEY=file_datalab",
                        'VERTEX_API_KEY="file_vertex"',
                        "export GOOGLE_API_KEY=file_google",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"DATALAB_API_KEY": "shell_datalab"}, clear=False):
                loaded = load_env_file(env_path)

                self.assertEqual(os.environ["DATALAB_API_KEY"], "shell_datalab")
                self.assertEqual(os.environ["VERTEX_API_KEY"], "file_vertex")
                self.assertEqual(os.environ["GOOGLE_API_KEY"], "file_google")
                self.assertNotIn("DATALAB_API_KEY", loaded)


def _load_sample() -> dict:
    return _load_json("examples/chapter_extraction.sample.json")


def _load_json(relative_path: str) -> dict:
    with (ROOT / relative_path).open("r", encoding="utf-8") as file:
        return json.load(file)


class FakeVeoClient:
    def __init__(self) -> None:
        self.submitted_count = 0
        self.start_frames = []

    def submit_video_generation(
        self,
        job: dict,
        options: VeoGenerationOptions,
        start_frame_path: Path | None = None,
    ) -> dict:
        self.submitted_count += 1
        if start_frame_path:
            self.start_frames.append(start_frame_path)
        return {"job_id": job["job_id"]}

    def poll_video_generation(self, operation: dict, options: VeoGenerationOptions) -> dict:
        return operation

    def save_generated_video(self, operation: dict, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"generated-video")


if __name__ == "__main__":
    unittest.main()
