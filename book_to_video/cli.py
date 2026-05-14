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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-to-video",
        description="Plan textbook chapter videos as 2-minute episodes made from 8-second clips.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "plan":
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


if __name__ == "__main__":
    main()
