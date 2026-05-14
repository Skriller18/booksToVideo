# Planning Artifacts

These JSON files are the contract between extraction, planning, generation, and stitching.

## `chapter_extraction.json`

Input to the MVP planner. In the current MVP this comes from Datalab's Document Conversion API using `output_format=json`.

Required fields:

- `chapter_id`
- `title`
- `topics`

Each topic should include:

- `topic_id`
- `title`
- `source_pages`
- `text`
- `learning_goal`
- `illustrations`

Each illustration should include:

- `illustration_id`
- `path`
- `caption`
- `page_number`

Future OCR adapters should also add bounding boxes, OCR confidence, page image paths, and crop coordinates.

## Datalab Extraction

Use:

```bash
export DATALAB_API_KEY="your_key"

python3 -m book_to_video.cli extract-datalab \
  --pdf path/to/chapter.pdf \
  --output-dir runs/chapter_ocr
```

The command calls Datalab `POST /api/v1/convert`, polls `request_check_url`, saves `raw_datalab_convert.json`, decodes Datalab `images` into `assets/`, and writes `chapter_extraction.json`.

The implementation deliberately uses Datalab Convert rather than the deprecated OCR endpoint because Datalab's current docs recommend Convert JSON for programmatic block access, bounding boxes, block types, and images.

## `episode_plan.json`

Defines the chapter as a series of 2-minute topic episodes.

Important fields:

- `episode_id`
- `title`
- `duration_seconds`
- `clip_count`
- `learning_goal`
- `source_pages`
- `source_topic_ids`
- `illustrations`
- `micro_drama_arc`

If `--episode-count` is larger than the extracted topic count, the planner expands larger topics into progressive parts.

## `storyboard.json`

Defines every 8-second clip beat.

Important fields:

- `global_clip_index`
- `episode_clip_index`
- `duration_seconds`
- `narration`
- `voice_profile`
- `audio_direction`
- `visual_beat`
- `veo_prompt`
- `negative_prompt`
- `reference_illustrations`

This file should be editable by a curriculum/content reviewer before generation. `narration` is the intended native Veo spoken line, not a separate TTS script.

## `veo_manifest.json`

Defines pending video generation jobs.

Important fields:

- `job_id`
- `prompt`
- `negative_prompt`
- `audio.mode`
- `audio.spoken_line`
- `audio.voice_profile`
- `audio.audio_direction`
- `reference_images`
- `output_path`
- `status`

This is the input for the future Veo worker.

The MVP assumes Veo-native audio. Each job repeats the shared voice profile so a batch of 200-300 clips keeps the same Indian classroom teacher tone as consistently as possible.

## `stitch_manifest.json`

Defines how clips become episode videos and how episode videos become the final chapter export.

Important fields:

- `episodes[].clip_paths`
- `episodes[].output_video`
- `chapter_playlist.output_video`
- `chapter_playlist.episode_paths`

Run a dry-run before generated clips exist:

```bash
python3 -m book_to_video.cli stitch \
  --stitch-manifest runs/chapter_plan/stitch_manifest.json \
  --media-root runs/chapter_plan \
  --output-dir runs/chapter_plan \
  --dry-run
```

After clips are present under the manifest's `clips/` paths, run:

```bash
python3 -m book_to_video.cli stitch \
  --stitch-manifest runs/chapter_plan/stitch_manifest.json \
  --media-root runs/chapter_plan \
  --output-dir runs/chapter_plan
```

By default the stitcher re-encodes with H.264/AAC for playback compatibility. Use `--copy-codecs` only when all clips have identical encoding and dimensions.

For development-only smoke tests, create local placeholder clips from `veo_manifest.json`:

```bash
python3 -m book_to_video.cli mock-clips \
  --veo-manifest runs/chapter_plan/veo_manifest.json \
  --media-root runs/chapter_plan \
  --duration 0.2
```
