from __future__ import annotations

import argparse
from pathlib import Path

from .io_utils import read_json, write_json
from .pipeline import build_planning_artifacts


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


if __name__ == "__main__":
    main()

