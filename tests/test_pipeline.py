import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from book_to_video.cli import _incomplete_veo_job_ids, load_env_file
from book_to_video.datalab_extractor import normalize_datalab_convert_result
from book_to_video.pipeline import build_planning_artifacts
from book_to_video.prompts import build_audio_direction, sanitize_veo_text
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

    def test_veo_text_sanitizer_removes_real_person_author_reference(self) -> None:
        text = (
            "Step 4: The Boy Who Broke the Bank Speaker icon indicating audio content. "
            "Letter A icon indicating audio content. Ruskin Bond is one of India's most loved writers."
        )

        sanitized = sanitize_veo_text(text)
        audio_direction = build_audio_direction(text)

        self.assertNotIn("Ruskin Bond", sanitized)
        self.assertNotIn("Ruskin Bond", audio_direction)
        self.assertNotIn("Speaker icon", sanitized)
        self.assertIn("The author is one of", sanitized)

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

    def test_datalab_json_children_normalizes_without_markdown(self) -> None:
        datalab_result = {
            "status": "complete",
            "success": True,
            "output_format": "json",
            "markdown": None,
            "json": {
                "children": [
                    {
                        "id": "/page/0/Page/0",
                        "block_type": "Page",
                        "html": "<h1>Duplicated aggregate text</h1>",
                        "children": [
                            {
                                "id": "/page/0/SectionHeader/0",
                                "block_type": "SectionHeader",
                                "html": "<h1>The Boy Who Broke the Bank</h1>",
                            },
                            {
                                "id": "/page/0/Text/1",
                                "block_type": "Text",
                                "html": "<p>Nathu swept the steps of the bank.</p>",
                            },
                        ],
                    },
                    {
                        "id": "/page/1/Page/1",
                        "block_type": "Page",
                        "children": [
                            {
                                "id": "/page/1/Text/0",
                                "block_type": "Text",
                                "page": 1,
                                "html": "<p>The rumour spread through the bazaar.</p>",
                            }
                        ],
                    },
                ],
                "metadata": {"page_stats": [{"page_id": 0}, {"page_id": 1}]},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            chapter = normalize_datalab_convert_result(
                datalab_result=datalab_result,
                source_pdf="story.pdf",
                output_dir=Path(tmp),
            )

            self.assertEqual(len(chapter["pages"]), 2)
            self.assertEqual(chapter["pages"][0]["page_number"], 1)
            self.assertEqual(chapter["pages"][0]["title"], "The Boy Who Broke the Bank")
            self.assertIn("Nathu swept the steps", chapter["pages"][0]["text"])
            self.assertNotIn("Duplicated aggregate text", chapter["pages"][0]["text"])

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

    def test_veo_generation_sanitizes_existing_manifest_before_submit(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "Context: Ruskin Bond is one of India's most loved writers.",
                    "audio": {
                        "spoken_line": "Step 1: Ruskin Bond is one of India's most loved writers.",
                    },
                    "output_path": "clips/clip_0001.mp4",
                    "status": "pending",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeVeoClient()
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=Path(tmp),
                options=VeoGenerationOptions(poll_interval_seconds=0, max_polls=1, continuity_enabled=False),
                client=fake_client,
            )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertNotIn("Ruskin Bond", fake_client.submitted_prompts[0])
            self.assertNotIn("Ruskin Bond", manifest["jobs"][0]["prompt"])
            self.assertNotIn("Ruskin Bond", manifest["jobs"][0]["audio"]["spoken_line"])

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

    def test_veo_generation_reruns_completed_job_when_output_missing(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "Completed in manifest but missing on disk.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "completed",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeVeoClient()
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=Path(tmp),
                options=VeoGenerationOptions(poll_interval_seconds=0, max_polls=1, continuity_enabled=False),
                client=fake_client,
            )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertEqual(fake_client.submitted_job_ids, ["veo_0001"])
            self.assertEqual(manifest["jobs"][0]["status"], "completed")
            self.assertTrue((Path(tmp) / "clips/clip_0001.mp4").exists())

    def test_veo_generation_failed_only_reruns_failed_jobs(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "Already done.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "completed",
                },
                {
                    "job_id": "veo_0002",
                    "duration_seconds": 8,
                    "prompt": "Try this one again.",
                    "output_path": "clips/clip_0002.mp4",
                    "status": "failed",
                    "error": "Veo operation completed without generated_videos",
                },
                {
                    "job_id": "veo_0003",
                    "duration_seconds": 8,
                    "prompt": "Not ready yet.",
                    "output_path": "clips/clip_0003.mp4",
                    "status": "pending",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed_path = root / "clips/clip_0001.mp4"
            completed_path.parent.mkdir(parents=True)
            completed_path.write_bytes(b"existing-video")

            fake_client = FakeVeoClient()
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=root,
                options=VeoGenerationOptions(
                    poll_interval_seconds=0,
                    max_polls=1,
                    continuity_enabled=False,
                    failed_only=True,
                ),
                client=fake_client,
            )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertEqual(result["skipped_clip_count"], 2)
            self.assertEqual(fake_client.submitted_job_ids, ["veo_0002"])
            self.assertEqual(manifest["jobs"][1]["status"], "completed")
            self.assertNotIn("error", manifest["jobs"][1])
            self.assertEqual(manifest["jobs"][2]["status"], "pending")

    def test_veo_generation_job_id_runs_only_selected_job(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "Skip this failed job.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "failed",
                },
                {
                    "job_id": "veo_0002",
                    "duration_seconds": 8,
                    "prompt": "Run only this failed job.",
                    "output_path": "clips/clip_0002.mp4",
                    "status": "failed",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeVeoClient()
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=Path(tmp),
                options=VeoGenerationOptions(
                    poll_interval_seconds=0,
                    max_polls=1,
                    continuity_enabled=False,
                    job_ids=("veo_0002",),
                ),
                client=fake_client,
            )

            self.assertEqual(result["generated_clip_count"], 1)
            self.assertEqual(result["skipped_clip_count"], 1)
            self.assertEqual(fake_client.submitted_job_ids, ["veo_0002"])
            self.assertEqual(manifest["jobs"][0]["status"], "failed")
            self.assertEqual(manifest["jobs"][1]["status"], "completed")

    def test_veo_generation_writes_diagnostics_when_operation_has_no_videos(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "duration_seconds": 8,
                    "prompt": "This response will have no videos.",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "pending",
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = generate_veo_clips_from_manifest(
                veo_manifest=manifest,
                media_root=root,
                options=VeoGenerationOptions(
                    poll_interval_seconds=0,
                    max_polls=1,
                    continuity_enabled=False,
                ),
                client=FakeVeoClientWithoutGeneratedVideos(),
            )

            diagnostics_path = root / "veo_diagnostics" / "veo_0001_operation.json"
            diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
            self.assertEqual(result["failed_clip_count"], 1)
            self.assertTrue(diagnostics_path.exists())
            self.assertEqual(diagnostics["job"]["job_id"], "veo_0001")
            self.assertEqual(diagnostics["operation"]["done"], True)
            self.assertIn("diagnostics", manifest["jobs"][0]["error"])

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

    def test_incomplete_veo_job_ids_reports_failed_and_missing_outputs(self) -> None:
        manifest = {
            "jobs": [
                {
                    "job_id": "veo_0001",
                    "output_path": "clips/clip_0001.mp4",
                    "status": "completed",
                },
                {
                    "job_id": "veo_0002",
                    "output_path": "clips/clip_0002.mp4",
                    "status": "completed",
                },
                {
                    "job_id": "veo_0003",
                    "output_path": "clips/clip_0003.mp4",
                    "status": "failed",
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "clips/clip_0001.mp4"
            output_path.parent.mkdir(parents=True)
            output_path.write_bytes(b"existing-video")

            self.assertEqual(
                _incomplete_veo_job_ids(manifest, root),
                ["veo_0002", "veo_0003"],
            )


def _load_sample() -> dict:
    return _load_json("examples/chapter_extraction.sample.json")


def _load_json(relative_path: str) -> dict:
    with (ROOT / relative_path).open("r", encoding="utf-8") as file:
        return json.load(file)


class FakeVeoClient:
    def __init__(self) -> None:
        self.submitted_count = 0
        self.submitted_job_ids = []
        self.submitted_prompts = []
        self.start_frames = []

    def submit_video_generation(
        self,
        job: dict,
        options: VeoGenerationOptions,
        start_frame_path: Path | None = None,
    ) -> dict:
        self.submitted_count += 1
        self.submitted_job_ids.append(job["job_id"])
        self.submitted_prompts.append(job["prompt"])
        if start_frame_path:
            self.start_frames.append(start_frame_path)
        return {"job_id": job["job_id"]}

    def poll_video_generation(self, operation: dict, options: VeoGenerationOptions) -> dict:
        return operation

    def save_generated_video(self, operation: dict, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"generated-video")


class FakeVeoClientWithoutGeneratedVideos:
    def submit_video_generation(
        self,
        job: dict,
        options: VeoGenerationOptions,
        start_frame_path: Path | None = None,
    ) -> object:
        return FakeOperation(name=f"operations/{job['job_id']}")

    def poll_video_generation(self, operation: object, options: VeoGenerationOptions) -> object:
        return operation


class FakeOperation:
    def __init__(self, name: str) -> None:
        self.name = name
        self.done = True
        self.response = FakeOperationResponse()


class FakeOperationResponse:
    def __init__(self) -> None:
        self.generated_videos = []


if __name__ == "__main__":
    unittest.main()
