# Books To Video MVP

Pipeline MVP for turning a textbook chapter into a sequence of short learning videos.

The MVP focuses on the planning layer before expensive generation:

```text
chapter_extraction.json
  -> episode_plan.json
  -> storyboard.json
  -> veo_manifest.json
  -> stitch_manifest.json
```

## Why This Shape

A chapter is treated as a micro-drama series:

- One chapter becomes multiple topic episodes.
- Each topic episode targets about 2 minutes.
- Each 2-minute episode is made from 15 Veo clips.
- Each Veo clip is a focused 8-second visual beat.

This keeps educational coverage, prompt generation, video generation, and stitching traceable.

## Quick Start

Run the sample pipeline:

```bash
python3 -m book_to_video.cli plan \
  --chapter-json examples/chapter_extraction.sample.json \
  --output-dir runs/sample
```

Run a 20-episode chapter plan, which produces 300 pending Veo clip jobs:

```bash
python3 -m book_to_video.cli plan \
  --chapter-json examples/chapter_extraction.sample.json \
  --output-dir runs/sample_20 \
  --episode-count 20
```

Generated files:

- `runs/sample/episode_plan.json`
- `runs/sample/storyboard.json`
- `runs/sample/veo_manifest.json`
- `runs/sample/stitch_manifest.json`

See [docs/artifacts.md](docs/artifacts.md) for the JSON contract.

## Test

```bash
python3 -m unittest
```

## Current Scope

Implemented:

- JSON schemas as dataclasses
- rule-based episode segmentation
- 15-clip storyboard generation per episode
- Veo prompt manifest generation
- stitch manifest generation

Stubbed boundaries:

- OCR/layout extraction
- illustration cropping
- LLM-based segmentation/refinement
- Veo API calls
- ffmpeg stitching

These are intentionally separated so real providers can be added without changing the planning artifacts.
