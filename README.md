# Proof, Please

Proof, Please is an experimental lab for checking health claims made in podcast transcripts and grounding those claims in peer-reviewed evidence.

The core idea is simple: extract concrete claims from transcript text, query scientific literature, and summarize where research consensus appears to be strong, mixed, or unclear.

## Current Status

- Transcript ingestion/normalization prototype:
  - `skills/get-transcript-from-url/scripts/extract_web_transcript.py`
  - `scripts/normalize_raw_transcript_segments.py`
- Claim extraction and query-generation prototype:
  - CLI entrypoint: `uv run proof-please ...`
  - Pipeline modules: `src/proof_please/pipeline/`
  - Core adapters/shared APIs: `src/proof_please/core/`
- Core app commands:
  - `uv run proof-please config`
  - `uv run proof-please init-db`
  - `uv run proof-please extract-claims ...`
- Local DuckDB schema bootstrap in `data/proof_please.duckdb`.

## Documentation

- `docs/README.md`: docs index
- `docs/transcript_formats.md`: raw + normalized transcript formats and file layout
- `docs/extracting_health_claims.md`: current claims pipeline architecture and command usage

## Consensus API

This project is designed to use the Consensus API to fetch relevant papers and metadata for each claim:

- Product page: `https://consensus.app/home/api/`
- API docs: `https://docs.consensus.app/reference/v1_quick_search`
- Current reference endpoint: `GET https://api.consensus.app/v1/quick_search`

Note: Consensus API access is application-based, so you may need approved access before live calls are possible.
Current prototype code does not yet call the Consensus API directly.

## Setup

```bash
uv sync
```

## CLI Commands

```bash
just sync
just init-db
just run config
uv run proof-please --help
uv run proof-please extract-claims --help
uv run proof-please generate-queries --help
uv run proof-please run-pipeline --help
```

## Streamlit Data Explorer

Use Streamlit to debug end-to-end links between transcript segments, extracted claims, and generated queries.

```bash
just explore-data
# or
uv run streamlit run src/proof_please/explorer/app.py
```

Default artifact paths used by the explorer:

- Claims: `data/claims.jsonl`
- Queries: `data/claim_queries.jsonl`
- Transcript source: `data/transcripts/norm/`

The app is organized into:

- **Claims**: filter claims, inspect evidence, and preview linked queries.
- **Queries**: inspect each query and jump back to its linked claim and transcript evidence.
- **Diagnostics**: surface orphan query links, missing transcript documents, and missing `seg_id` references.

Model backend flags:

- Primary: `--backend-url`
- Backward-compatible alias: `--ollama-url`

Normalize raw transcript JSON into segmented transcript JSON:

```bash
uv run python scripts/normalize_raw_transcript_segments.py --help
```

## Configuration

- Environment variables use the `PP_` prefix.
- Default database path is `data/proof_please.duckdb`.

## Development Approach

This repository is intentionally iterative and experimental. Expect small, reversible changes as the problem definition improves with real transcripts and evidence-review feedback.
