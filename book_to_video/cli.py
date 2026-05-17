from __future__ import annotations

import argparse
import os
from pathlib import Path

from .datalab_client import DatalabConvertClient, DatalabConvertOptions
from .datalab_extractor import normalize_datalab_convert_result
from .io_utils import read_json, write_json
from .pipeline import build_planning_artifacts
from .placeholders import create_placeholder_clips
from .stitcher import stitch_from_manifest
from .veo_client import DEFAULT_VEO_MODEL, VeoGenerationOptions, generate_veo_clips_from_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-to-video",
        description="Plan textbook chapter videos as 2-minute episodes made from 8-second clips.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file. Defaults to .env in the current working directory if present.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="Run extraction, planning, Veo generation, and stitching as one pipeline.",
    )
    run.add_argument("--pdf", help="Path to chapter PDF. Required unless --raw-json is provided.")
    run.add_argument("--raw-json", help="Use a saved Datalab result instead of calling the API.")
    run.add_argument("--output-dir", required=True, help="Directory where all pipeline artifacts are written.")
    run.add_argument("--chapter-id", help="Optional stable chapter id.")
    run.add_argument("--chapter-title", help="Optional chapter title override.")
    run.add_argument("--mode", default="accurate", choices=("fast", "balanced", "accurate"))
    run.add_argument("--max-pages", type=int, default=None)
    run.add_argument("--page-range", default=None, help='Datalab page range, for example "0-5,10".')
    run.add_argument("--poll-interval", type=int, default=2)
    run.add_argument("--max-polls", type=int, default=300)
    run.add_argument("--skip-cache", action="store_true")
    run.add_argument("--episode-count", type=int, default=None)
    run.add_argument("--clips-per-episode", type=int, default=15)
    run.add_argument("--clip-duration", type=int, default=8, choices=(4, 6, 8))
    run.add_argument("--veo-model", default=DEFAULT_VEO_MODEL, help=f"Veo model id. Default: {DEFAULT_VEO_MODEL}.")
    run.add_argument("--veo-limit", type=int, default=None, help="Generate only the first N runnable clips.")
    run.add_argument("--veo-poll-interval", type=int, default=10)
    run.add_argument("--veo-max-polls", type=int, default=60)
    run.add_argument("--aspect-ratio", default="16:9", choices=("16:9", "9:16"))
    run.add_argument("--resolution", default="720p", choices=("720p", "1080p", "4k"))
    run.add_argument("--person-generation", default="allow_all")
    run.add_argument("--overwrite-existing", action="store_true")
    run.add_argument("--no-continuity", action="store_true", help="Do not feed prior clip frames into Veo.")
    run.add_argument("--continuity-scope", default="episode", choices=("episode", "chapter"))
    run.add_argument("--mock-clips", action="store_true", help="Create placeholder clips instead of calling Veo.")
    run.add_argument("--mock-duration", type=float, default=None, help="Override placeholder duration.")
    run.add_argument("--episodes-only", action="store_true", help="Skip the full chapter playlist video.")
    run.add_argument("--copy-codecs", action="store_true")

    plan = subparsers.add_parser("plan", help="Build episode, storyboard, Veo, and stitch manifests.")
    plan.add_argument("--chapter-json", required=True, help="Path to chapter_extraction.json.")
    plan.add_argument("--output-dir", required=True, help="Directory where planning artifacts are written.")
    plan.add_argument(
        "--episode-count",
        type=int,
        default=None,
        help="Optional target number of topic episodes. Defaults to one episode per detected topic.",
    )
    plan.add_argument(
        "--clips-per-episode",
        type=int,
        default=15,
        help="Number of 8-second clips per 2-minute episode. Default: 15.",
    )
    plan.add_argument(
        "--clip-duration",
        type=int,
        default=8,
        choices=(4, 6, 8),
        help="Clip duration in seconds. Default: 8.",
    )

    extract = subparsers.add_parser(
        "extract-datalab",
        help="Extract chapter text and illustrations using Datalab Convert API.",
    )
    extract.add_argument("--pdf", help="Path to chapter PDF. Required unless --raw-json is provided.")
    extract.add_argument("--raw-json", help="Normalize a saved Datalab result instead of calling the API.")
    extract.add_argument("--output-dir", required=True, help="Directory where extraction artifacts are written.")
    extract.add_argument("--chapter-id", help="Optional stable chapter id.")
    extract.add_argument("--chapter-title", help="Optional chapter title override.")
    extract.add_argument("--mode", default="accurate", choices=("fast", "balanced", "accurate"))
    extract.add_argument("--max-pages", type=int, default=None)
    extract.add_argument("--page-range", default=None, help='Datalab page range, for example "0-5,10".')
    extract.add_argument("--poll-interval", type=int, default=2)
    extract.add_argument("--max-polls", type=int, default=300)
    extract.add_argument("--skip-cache", action="store_true")

    stitch = subparsers.add_parser(
        "stitch",
        help="Stitch generated 8-second clips into episode videos and an optional chapter video.",
    )
    stitch.add_argument("--stitch-manifest", required=True, help="Path to stitch_manifest.json.")
    stitch.add_argument(
        "--media-root",
        help="Root directory for relative clip paths. Defaults to the manifest directory.",
    )
    stitch.add_argument(
        "--output-dir",
        help="Root directory for relative output paths. Defaults to the manifest directory.",
    )
    stitch.add_argument("--dry-run", action="store_true", help="Report planned stitching without running ffmpeg.")
    stitch.add_argument(
        "--episodes-only",
        action="store_true",
        help="Only stitch episode videos; skip the full chapter playlist video.",
    )
    stitch.add_argument(
        "--copy-codecs",
        action="store_true",
        help="Use ffmpeg stream copy instead of re-encoding. Faster but less tolerant.",
    )

    placeholders = subparsers.add_parser(
        "mock-clips",
        help="Create local placeholder MP4 clips from veo_manifest.json for end-to-end stitching tests.",
    )
    placeholders.add_argument("--veo-manifest", required=True, help="Path to veo_manifest.json.")
    placeholders.add_argument(
        "--media-root",
        help="Root directory for relative clip output paths. Defaults to the manifest directory.",
    )
    placeholders.add_argument("--limit", type=int, default=None, help="Only create the first N clips.")
    placeholders.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Override clip duration for faster local tests.",
    )

    veo = subparsers.add_parser(
        "generate-veo",
        help="Generate real Veo clips from veo_manifest.json using the Gemini API.",
    )
    veo.add_argument("--veo-manifest", required=True, help="Path to veo_manifest.json.")
    veo.add_argument(
        "--media-root",
        help="Root directory for relative clip output paths. Defaults to the manifest directory.",
    )
    veo.add_argument("--model", default=DEFAULT_VEO_MODEL, help=f"Veo model id. Default: {DEFAULT_VEO_MODEL}.")
    veo.add_argument("--limit", type=int, default=None, help="Generate only the first N runnable clips.")
    veo.add_argument("--poll-interval", type=int, default=10, help="Seconds between Veo operation polls.")
    veo.add_argument("--max-polls", type=int, default=60, help="Maximum polls per clip before failing it.")
    veo.add_argument("--aspect-ratio", default="16:9", choices=("16:9", "9:16"))
    veo.add_argument("--resolution", default="720p", choices=("720p", "1080p", "4k"))
    veo.add_argument("--person-generation", default="allow_all")
    veo.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Regenerate clips even when the output MP4 already exists.",
    )
    veo.add_argument("--no-continuity", action="store_true", help="Do not feed prior clip frames into Veo.")
    veo.add_argument("--continuity-scope", default="episode", choices=("episode", "chapter"))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(Path(args.env_file) if args.env_file else Path.cwd() / ".env")

    if args.command == "run":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if args.raw_json:
            datalab_result = read_json(Path(args.raw_json))
            source_pdf = args.pdf or datalab_result.get("source_pdf") or "unknown.pdf"
        else:
            if not args.pdf:
                parser.error("--pdf is required unless --raw-json is provided")
            api_key = os.environ.get("DATALAB_API_KEY", "")
            client = DatalabConvertClient(api_key=api_key)
            datalab_options = DatalabConvertOptions(
                output_format="json",
                mode=args.mode,
                paginate=True,
                disable_image_extraction=False,
                disable_image_captions=False,
                max_pages=args.max_pages,
                page_range=args.page_range,
                skip_cache=args.skip_cache,
            )
            datalab_result = client.convert_pdf(
                Path(args.pdf),
                options=datalab_options,
                poll_interval_seconds=args.poll_interval,
                max_polls=args.max_polls,
            )
            source_pdf = args.pdf
            write_json(output_dir / "raw_datalab_convert.json", datalab_result)

        chapter = normalize_datalab_convert_result(
            datalab_result=datalab_result,
            source_pdf=source_pdf,
            output_dir=output_dir,
            chapter_id=args.chapter_id,
            chapter_title=args.chapter_title,
        )
        write_json(output_dir / "chapter_extraction.json", chapter)

        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=args.episode_count,
            clips_per_episode=args.clips_per_episode,
            clip_duration_seconds=args.clip_duration,
        )
        write_json(output_dir / "episode_plan.json", artifacts["episode_plan"])
        write_json(output_dir / "storyboard.json", artifacts["storyboard"])
        write_json(output_dir / "veo_manifest.json", artifacts["veo_manifest"])
        write_json(output_dir / "stitch_manifest.json", artifacts["stitch_manifest"])

        if args.mock_clips:
            clip_result = create_placeholder_clips(
                veo_manifest=artifacts["veo_manifest"],
                media_root=output_dir,
                duration_override=args.mock_duration,
            )
            write_json(output_dir / "mock_clips_result.json", clip_result)
        else:
            veo_options = VeoGenerationOptions(
                model=args.veo_model,
                aspect_ratio=args.aspect_ratio,
                resolution=args.resolution,
                person_generation=args.person_generation,
                poll_interval_seconds=args.veo_poll_interval,
                max_polls=args.veo_max_polls,
                limit=args.veo_limit,
                skip_existing=not args.overwrite_existing,
                continuity_enabled=not args.no_continuity,
                continuity_scope=args.continuity_scope,
            )
            clip_result = generate_veo_clips_from_manifest(
                veo_manifest=artifacts["veo_manifest"],
                media_root=output_dir,
                options=veo_options,
                persist_manifest=lambda payload: write_json(output_dir / "veo_manifest.json", payload),
            )
            write_json(output_dir / "veo_generation_result.json", clip_result)

        stitch_manifest = read_json(output_dir / "stitch_manifest.json")
        stitch_result = stitch_from_manifest(
            stitch_manifest=stitch_manifest,
            media_root=output_dir,
            output_root=output_dir,
            include_chapter=not args.episodes_only,
            copy_codecs=args.copy_codecs,
        )
        write_json(output_dir / "stitch_result.json", stitch_result)
        print(f"Completed pipeline; wrote artifacts and videos under {output_dir}")
    elif args.command == "plan":
        chapter_path = Path(args.chapter_json)
        output_dir = Path(args.output_dir)
        chapter = read_json(chapter_path)
        artifacts = build_planning_artifacts(
            chapter,
            target_episode_count=args.episode_count,
            clips_per_episode=args.clips_per_episode,
            clip_duration_seconds=args.clip_duration,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "episode_plan.json", artifacts["episode_plan"])
        write_json(output_dir / "storyboard.json", artifacts["storyboard"])
        write_json(output_dir / "veo_manifest.json", artifacts["veo_manifest"])
        write_json(output_dir / "stitch_manifest.json", artifacts["stitch_manifest"])

        print(f"Wrote planning artifacts to {output_dir}")
    elif args.command == "extract-datalab":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if args.raw_json:
            datalab_result = read_json(Path(args.raw_json))
            source_pdf = args.pdf or datalab_result.get("source_pdf") or "unknown.pdf"
        else:
            if not args.pdf:
                parser.error("--pdf is required unless --raw-json is provided")
            api_key = os.environ.get("DATALAB_API_KEY", "")
            client = DatalabConvertClient(api_key=api_key)
            options = DatalabConvertOptions(
                output_format="json",
                mode=args.mode,
                paginate=True,
                disable_image_extraction=False,
                disable_image_captions=False,
                max_pages=args.max_pages,
                page_range=args.page_range,
                skip_cache=args.skip_cache,
            )
            datalab_result = client.convert_pdf(
                Path(args.pdf),
                options=options,
                poll_interval_seconds=args.poll_interval,
                max_polls=args.max_polls,
            )
            source_pdf = args.pdf
            write_json(output_dir / "raw_datalab_convert.json", datalab_result)

        chapter = normalize_datalab_convert_result(
            datalab_result=datalab_result,
            source_pdf=source_pdf,
            output_dir=output_dir,
            chapter_id=args.chapter_id,
            chapter_title=args.chapter_title,
        )
        write_json(output_dir / "chapter_extraction.json", chapter)
        print(f"Wrote Datalab chapter extraction to {output_dir / 'chapter_extraction.json'}")
    elif args.command == "stitch":
        manifest_path = Path(args.stitch_manifest)
        stitch_manifest = read_json(manifest_path)
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        output_dir = Path(args.output_dir) if args.output_dir else manifest_path.parent

        result = stitch_from_manifest(
            stitch_manifest=stitch_manifest,
            media_root=media_root,
            output_root=output_dir,
            dry_run=args.dry_run,
            include_chapter=not args.episodes_only,
            copy_codecs=args.copy_codecs,
        )
        write_json(output_dir / "stitch_result.json", result)
        action = "Planned" if args.dry_run else "Completed"
        print(f"{action} stitching; wrote {output_dir / 'stitch_result.json'}")
    elif args.command == "mock-clips":
        manifest_path = Path(args.veo_manifest)
        veo_manifest = read_json(manifest_path)
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        result = create_placeholder_clips(
            veo_manifest=veo_manifest,
            media_root=media_root,
            limit=args.limit,
            duration_override=args.duration,
        )
        write_json(media_root / "mock_clips_result.json", result)
        print(f"Created {result['created_clip_count']} placeholder clips under {media_root}")
    elif args.command == "generate-veo":
        manifest_path = Path(args.veo_manifest)
        veo_manifest = read_json(manifest_path)
        media_root = Path(args.media_root) if args.media_root else manifest_path.parent
        options = VeoGenerationOptions(
            model=args.model,
            aspect_ratio=args.aspect_ratio,
            resolution=args.resolution,
            person_generation=args.person_generation,
            poll_interval_seconds=args.poll_interval,
            max_polls=args.max_polls,
            limit=args.limit,
            skip_existing=not args.overwrite_existing,
            continuity_enabled=not args.no_continuity,
            continuity_scope=args.continuity_scope,
        )

        result = generate_veo_clips_from_manifest(
            veo_manifest=veo_manifest,
            media_root=media_root,
            options=options,
            persist_manifest=lambda payload: write_json(manifest_path, payload),
        )
        write_json(media_root / "veo_generation_result.json", result)
        print(
            "Generated "
            f"{result['generated_clip_count']} clips, skipped {result['skipped_clip_count']}, "
            f"failed {result['failed_clip_count']}; wrote {media_root / 'veo_generation_result.json'}"
        )

def load_env_file(path: Path, override: bool = False) -> dict[str, str]:
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {line_number} in {path}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = _parse_env_value(value.strip())
        if not key:
            raise ValueError(f"Invalid .env line {line_number} in {path}: empty key")
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def _parse_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


if __name__ == "__main__":
    main()
