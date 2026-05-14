# Planning Artifacts

These JSON files are the contract between extraction, planning, generation, and stitching.

## `chapter_extraction.json`

Input to the MVP planner. This should come from OCR/layout extraction.

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
- `visual_beat`
- `veo_prompt`
- `negative_prompt`
- `reference_illustrations`

This file should be editable by a curriculum/content reviewer before generation.

## `veo_manifest.json`

Defines pending video generation jobs.

Important fields:

- `job_id`
- `prompt`
- `negative_prompt`
- `reference_images`
- `output_path`
- `status`

This is the input for the future Veo worker.

## `stitch_manifest.json`

Defines how clips become episode videos and how episode videos become the final chapter export.

Important fields:

- `episodes[].clip_paths`
- `episodes[].output_video`
- `chapter_playlist.output_video`
- `chapter_playlist.episode_paths`

