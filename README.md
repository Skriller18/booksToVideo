# Books To Video MVP

Pipeline MVP for turning a textbook chapter into a sequence of short learning videos.

The MVP focuses on the planning layer before expensive generation:

```text
Datalab Convert API
  -> chapter_extraction.json
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

Extract a chapter PDF through Datalab:

```bash
export DATALAB_API_KEY="your_key"

python3 -m book_to_video.cli extract-datalab \
  --pdf path/to/chapter.pdf \
  --output-dir runs/chapter_ocr
```

This writes:

- `runs/chapter_ocr/raw_datalab_convert.json`
- `runs/chapter_ocr/chapter_extraction.json`
- extracted illustration assets under `runs/chapter_ocr/assets/`

Normalize a saved Datalab response without calling the API:

```bash
python3 -m book_to_video.cli extract-datalab \
  --raw-json examples/datalab_convert.sample.json \
  --pdf light-and-shadows.pdf \
  --output-dir runs/datalab_sample
```

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

- illustration cropping
- LLM-based segmentation/refinement
- Veo API calls
- ffmpeg stitching

Datalab OCR/layout extraction is the first implemented provider boundary. The remaining pieces are intentionally separated so they can be added without changing the planning artifacts.
