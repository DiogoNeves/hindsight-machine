---
name: get-transcript-from-url
description: Fetch and normalize transcript content from webpage URLs into JSON with source metadata and raw transcript text. Use when asked to get, download, or fetch a transcript from a URL, especially for podcast transcript pages, and when output must follow the web__podcast_name__episode_title__episode_date__v1.json naming pattern.
---

# Get Transcript From URL

## Overview
Extract transcript page content from a URL and save normalized JSON for downstream processing.
Use `scripts/extract_web_transcript.py` for deterministic output and apply metadata overrides when site metadata is incomplete.

## Workflow
1. Validate the target URL and identify likely transcript pages (`/transcript`, `/podcast-transcripts`, episode pages).
2. Run the extractor script to fetch HTML, infer metadata, and write JSON.
3. If direct `requests` fetch is blocked (`403`/challenge page), rely on built-in `cloudscraper` fallback.
4. If metadata inference is weak, rerun with overrides (`--podcast-name`, `--episode-title`, `--episode-date`).
5. If anti-bot protection still blocks fetches, save HTML via browser or `cloudscraper` and rerun with `--html-file`.
6. Confirm output has non-empty `raw` content and expected filename format.

## Commands
Run with project dependencies via `uv`:

```bash
uv run \
  python skills/get-transcript-from-url/scripts/extract_web_transcript.py \
  "https://example.com/transcript-page" \
  --output-dir data/transcripts/raw
```

Override metadata when needed:

```bash
uv run \
  python skills/get-transcript-from-url/scripts/extract_web_transcript.py \
  "https://example.com/transcript-page" \
  --output-dir data/transcripts/raw \
  --podcast-name "The Ready State" \
  --episode-title "Layne Norton: Nutrition Research" \
  --episode-date "2022-10-20"
```

If direct fetch is blocked and fallback dependencies are not installed, run with one-off `cloudscraper`:

```bash
uv run --with cloudscraper \
  python skills/get-transcript-from-url/scripts/extract_web_transcript.py \
  "https://example.com/transcript-page" \
  --output-dir data/transcripts/raw
```

Use saved HTML when anti-bot protection still blocks automation:

```bash
uv run \
  python skills/get-transcript-from-url/scripts/extract_web_transcript.py \
  "https://thereadystate.com/podcast-transcripts/layne-norton/" \
  --html-file /path/to/page.html \
  --output-dir data/transcripts/raw
```

## Output Contract
Write a JSON file with this shape:

```json
{
  "doc_id": "web__podcast__episode__2022-10-20__v1",
  "source": {
    "type": "web_transcript",
    "url": "https://example.com/transcript-page",
    "retrieved_at": "2026-02-08"
  },
  "episode": {
    "podcast_name": "Podcast Name",
    "title": "Episode Title",
    "published_date": "2022-10-20"
  },
  "raw": "Full transcript text..."
}
```

Use filename pattern:

`web__<podcast_name>__<episode_title>__<episode_date>__v1.json`

## Notes
- Keep raw text faithful to page transcript content; avoid summarization.
- Prefer automatic metadata extraction first, then apply explicit overrides for correctness.
- Normalize names to URL-safe lowercase slugs in the output filename.
