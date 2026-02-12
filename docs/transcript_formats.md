# Transcript File Formats

This document describes the current transcript JSON formats used in this repository.

## Scope

These formats are currently part of a prototype ingestion and extraction flow.

- Raw transcript extraction script: `skills/get-transcript-from-url/scripts/extract_web_transcript.py`
- Raw -> normalized conversion script: `scripts/normalize_raw_transcript_segments.py`
- Normalized transcript consumer: `uv run proof-please extract-claims ...`
  - Consumer implementation modules: `src/proof_please/pipeline/` and `src/proof_please/core/`

For command usage and stage/module details, see `docs/extracting_health_claims.md`.

Both are temporary and expected to be replaced by a more scalable, source-agnostic implementation later.

## Directory Layout

- Raw transcripts: `data/transcripts/raw/`
- Normalized transcripts: `data/transcripts/norm/`
- Downstream artifacts (from normalized transcripts):
  - Claims: `data/claims.jsonl`
  - Claim validation queries: `data/claim_queries.jsonl`

Files usually keep the same filename in both directories.

## Raw Format (`data/transcripts/raw/*.json`)

Raw files preserve source metadata plus a single transcript blob.

```json
{
  "doc_id": "web__podcast-name__episode-title__2024-01-15__v1",
  "source": {
    "type": "web_transcript",
    "url": "https://example.com/podcast/transcripts/episode-title",
    "retrieved_at": "2026-02-08"
  },
  "episode": {
    "podcast_name": "Podcast Name",
    "title": "Episode Title",
    "published_date": "2024-01-15"
  },
  "raw": "Host: [0:00:04]\n\nWelcome to the show..."
}
```

### Notes

- `raw` is plain transcript text, not segmented JSON.
- Speaker + timestamp markers are embedded in text lines, for example:
  - `Host: [0:00:04]`
  - `Host: (0:00:04)`
  - `Guest: [0:00:06]`
- Timestamp parsing supports both `mm:ss` and `hh:mm:ss`.

## Normalized Format (`data/transcripts/norm/*.json`)

Normalized files convert the `raw` blob into timestamped segments.

```json
{
  "doc_id": "podcastname_episode-title_2024-01-15",
  "source": {
    "type": "web_transcript",
    "url": "https://example.com/podcast/transcripts/episode-title",
    "retrieved_at": "2026-02-08"
  },
  "episode": {
    "title": "Episode Title",
    "published_date": "2024-01-15"
  },
  "segments": [
    {
      "seg_id": "seg_000001",
      "speaker": "Host",
      "start_time_s": 4,
      "text": "Welcome to the show."
    }
  ]
}
```

### `doc_id` Derivation

`scripts/normalize_raw_transcript_segments.py` builds normalized `doc_id` as follows:

1. Preferred path (when episode metadata is present):
   - `<podcast_name_slug_without_dashes>_<episode_title_slug>_<published_date>`
2. Fallback path (from raw `doc_id`):
   - remove `web__` prefix
   - remove version suffix like `__v1`
   - replace `__` with `_`

## Segment Contract

Each entry in `segments` follows:

- `seg_id` (`string`): zero-padded sequential id (for example `seg_000001`).
- `speaker` (`string`): speaker label parsed from `Speaker: [timestamp]`.
- `start_time_s` (`integer`): start timestamp converted to seconds.
- `text` (`string`): utterance text until the next timestamped speaker marker.

## Current Normalization Rules

Implemented by `scripts/normalize_raw_transcript_segments.py`:

1. Detect marker lines in the form `Speaker: [hh:mm:ss]`, `Speaker: [mm:ss]`, `Speaker: (hh:mm:ss)`, or `Speaker: (mm:ss)`.
2. Start a new segment when a new speaker/timestamp marker is found.
3. Append following non-empty lines to that segment until the next marker.
4. Normalize intra-segment whitespace to single spaces.
5. Drop empty segments.
6. Keep `source` from raw input.
7. Keep only `episode.title` and `episode.published_date` in normalized output.
8. Generate sequential `seg_id` values (`seg_000001`, `seg_000002`, ...).

## File Naming Convention

Current naming pattern (raw and norm):

`web__<podcast_slug>__<episode_slug>__<YYYY-MM-DD>__v1.json`

Normalized files are currently written using the same filename as the source raw file.

## Known Limitations (Prototype)

- Assumes transcript text includes explicit speaker/timestamp markers.
- Does not infer speakers when markers are missing.
- Does not preserve paragraph breaks inside segment text.
- Normalized segments include only `start_time_s` (no explicit `end_time_s`).
- No cross-source schema adapter yet (single-source optimized).
