# Books To Video MVP

Pipeline MVP for turning a textbook chapter into a sequence of short learning videos.

The MVP keeps every step traceable from extraction through generation:

```text
Datalab Convert API
  -> chapter_extraction.json
  -> episode_plan.json
  -> storyboard.json
  -> veo_manifest.json
  -> generated clips
  -> stitch_manifest.json
  -> episode videos
  -> full chapter video
```

## Why This Shape

A chapter is treated as a micro-drama series:

- One chapter becomes multiple topic episodes.
- Each topic episode targets about 2 minutes.
- Each 2-minute episode is made from 15 Veo clips.
- Each Veo clip is a focused 8-second visual beat.

This keeps educational coverage, prompt generation, video generation, and stitching traceable.

## Quick Start

Install the optional provider SDK used for real Veo generation:

```bash
python3 -m pip install -r requirements.txt
```

Create a local `.env` file for API keys:

```bash
cp .env.example .env
```

Then edit `.env`:

```bash
DATALAB_API_KEY=your_datalab_key
VERTEX_API_KEY=your_gemini_or_vertex_api_key
```

The CLI loads `.env` from the current working directory automatically. You can also pass `--env-file path/to/.env`.

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

Run the full real pipeline from PDF to final chapter video:

```bash
export DATALAB_API_KEY="your_datalab_key"
export VERTEX_API_KEY="your_gemini_or_vertex_api_key"

python3 -m book_to_video.cli run \
  --pdf path/to/chapter.pdf \
  --output-dir runs/chapter_full \
  --episode-count 20
```

For a local smoke test without spending Veo credits, run the same pipeline with placeholder clips:

```bash
python3 -m book_to_video.cli run \
  --raw-json examples/datalab_convert.sample.json \
  --output-dir runs/smoke_full \
  --episode-count 1 \
  --clips-per-episode 1 \
  --mock-clips \
  --mock-duration 0.2
```

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

Check the stitching plan before clips exist:

```bash
python3 -m book_to_video.cli stitch \
  --stitch-manifest runs/sample_20/stitch_manifest.json \
  --media-root runs/sample_20 \
  --output-dir runs/sample_20 \
  --dry-run
```

For local end-to-end testing before Veo is connected, create placeholder clips:

```bash
python3 -m book_to_video.cli mock-clips \
  --veo-manifest runs/sample_20/veo_manifest.json \
  --media-root runs/sample_20
```

Generate real Veo clips through the Gemini API:

```bash
export GEMINI_API_KEY="your_key"

python3 -m book_to_video.cli generate-veo \
  --veo-manifest runs/sample_20/veo_manifest.json \
  --media-root runs/sample_20 \
  --limit 1
```

`generate-veo` accepts `VERTEX_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`.
Continuity is enabled by default: after each generated clip, the worker extracts its last frame into `continuity/` and sends that image as the starting frame for the next clip in the same episode. Use `--no-continuity` to disable this, or `--continuity-scope chapter` to carry continuity across episode boundaries.

Remove `--limit 1` when you are ready to generate every pending clip. The command updates `veo_manifest.json` after each clip, so it can be rerun to continue a partially completed chapter.

After Veo clips exist in `runs/sample_20/clips/`, stitch episodes and the full chapter video:

```bash
python3 -m book_to_video.cli stitch \
  --stitch-manifest runs/sample_20/stitch_manifest.json \
  --media-root runs/sample_20 \
  --output-dir runs/sample_20
```

This writes:

- `runs/sample_20/episodes/*.mp4`
- `runs/sample_20/chapter/full_chapter.mp4`
- `runs/sample_20/stitch_result.json`

For faster smoke tests, use `--duration 0.2` with `mock-clips` on a small episode plan.

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
- native Veo audio instructions per clip
- Gemini API Veo clip generation from `veo_manifest.json`
- resumable Veo manifest status updates
- previous-clip last-frame continuity for Veo generation
- stitch manifest generation
- ffmpeg-based episode and chapter stitching from manifests
- local placeholder clip generation for stitch testing before Veo is connected

Stubbed boundaries:

- illustration cropping
- LLM-based segmentation/refinement

Datalab OCR/layout extraction and Gemini API Veo generation are implemented provider boundaries. The remaining pieces are intentionally separated so they can be added without changing the planning artifacts.
