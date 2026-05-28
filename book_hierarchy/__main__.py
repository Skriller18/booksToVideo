from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .extractor import extract_hierarchy
from .io_utils import write_json
from .models import to_dict


def load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and (override or key not in os.environ):
            os.environ[key] = value


def _google_api_key() -> str:
    return (
        os.environ.get("VERTEX_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-hierarchy",
        description="Extract chapter/topic hierarchy from a full-book PDF into structured JSON.",
    )
    parser.add_argument("--pdf", required=True, help="Path to the book PDF.")
    parser.add_argument("--output", required=True, help="Output JSON file path.")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file. Defaults to .env in the current working directory if present.",
    )
    parser.add_argument(
        "--method",
        default=None,
        choices=("toc", "headings", "ai"),
        help="Force specific extraction method. Default: auto (TOC > headings > AI).",
    )
    parser.add_argument(
        "--gemini-key",
        default=None,
        help="Gemini API key for AI fallback. Also reads VERTEX_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY env vars.",
    )
    parser.add_argument(
        "--print-chapters",
        action="store_true",
        help="Print chapter titles and topic counts to stdout as a quick summary.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    env_path = Path(args.env_file) if args.env_file else Path.cwd() / ".env"
    load_env_file(env_path)

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    api_key = args.gemini_key or _google_api_key()

    method_label = args.method or "auto"
    print(f"Extracting hierarchy from: {pdf_path.name}")
    print(f"Method: {method_label}")
    print(f"Pages: reading...")

    hierarchy = extract_hierarchy(
        pdf_path=pdf_path,
        api_key=api_key or None,
        force_method=args.method,
    )

    output_path = Path(args.output)
    write_json(output_path, to_dict(hierarchy))

    chapter_count = len(hierarchy.chapters)
    total_topics = sum(len(ch.topics) for ch in hierarchy.chapters)
    print()
    print(f"Done. Method used: {hierarchy.extraction_method} (confidence: {hierarchy.extraction_confidence:.2f})")
    print(f"Chapters: {chapter_count}, Topics: {total_topics}, Pages: {hierarchy.page_count}")
    print(f"Written: {output_path}")

    if args.print_chapters:
        print()
        for ch in hierarchy.chapters:
            t_count = len(ch.topics)
            print(f"  [{ch.chapter_number}] {ch.title}  (pages {ch.page_start}-{ch.page_end}, {t_count} topics)")
            for t in ch.topics:
                print(f"       - {t.title}  (pages {t.page_start}-{t.page_end})")


if __name__ == "__main__":
    main()
