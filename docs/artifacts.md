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
- `asset_type`
- `is_lesson_asset`
- `rejection_reason`

The extraction layer classifies image assets before topic planning. Publisher
logos, QR codes, barcodes, audio icons, decorative marks, and other unrelated
assets are not attached to topics as lesson illustrations. The files may still
exist under `assets/` for traceability, but they should not appear in
storyboard `reference_illustrations` or Veo `reference_images`.

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
- `metadata.orchestrator`
- `metadata.illustration_policy`

This file should be editable by a curriculum/content reviewer before generation. `narration` is the intended native Veo spoken line, not a separate TTS script.

The storyboard is produced through an orchestrator contract that decides the
microdrama flow, what the teacher voice says, and whether an illustration should
be used. Clips that do not need a source illustration keep
`reference_illustrations` empty so Veo is guided by continuity and the prompt
instead of unrelated page images.

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
- `continuity.start_frame_path`
- `continuity.last_frame_path`
- `continuity.mode`

This is the input for the Veo worker:

```bash
export VERTEX_API_KEY="your_key"

python3 -m book_to_video.cli generate-veo \
  --veo-manifest runs/chapter_plan/veo_manifest.json \
  --media-root runs/chapter_plan \
  --limit 1
```

The Veo worker accepts `VERTEX_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`.

The command writes generated clips to each job's `output_path`, updates `status`, `operation_name`, `local_output_path`, and `continuity` in `veo_manifest.json`, and writes `veo_generation_result.json`. Use `--limit 1` for a cost-controlled smoke test, then remove it to generate all pending clips.

Continuity is enabled by default. After a clip is generated, the worker extracts its last frame with `ffmpeg`, saves it under `continuity/`, and sends it as the starting image for the next clip in the same episode. Use `--no-continuity` to disable this. Use `--continuity-scope chapter` only when the entire chapter should behave like one continuous visual scene.

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
