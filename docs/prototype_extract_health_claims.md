# Prototype: Extract Health Claims

This document explains the command structure in `scripts/prototype_extract_health_claims.py`.

## Purpose

The prototype supports:

1. Claim extraction from normalized transcript segments.
2. Validation query generation from claim rows.
3. A full end-to-end pipeline command.

It uses local Ollama models and writes JSONL artifacts in `data/`.

## Commands

Run help:

```bash
uv run python scripts/prototype_extract_health_claims.py --help
```

Available commands:

1. `extract-claims`
2. `generate-queries`
3. `run-pipeline`

## Command Details

### extract-claims

Runs only claim extraction and writes claims JSONL.

```bash
uv run python scripts/prototype_extract_health_claims.py extract-claims \
  --transcript data/transcripts/norm/web__the-ready-state__layne-norton__2022-10-20__v1.json \
  --models qwen3:4b \
  --output data/claims.jsonl \
  --no-list-claims
```

### generate-queries

Runs only query generation from an existing claims JSONL.

```bash
uv run python scripts/prototype_extract_health_claims.py generate-queries \
  --claims-input data/claims.jsonl \
  --query-model qwen3:4b \
  --queries-output data/claim_queries.jsonl \
  --no-list-queries
```

### run-pipeline

Runs extraction and query generation end-to-end.

```bash
uv run python scripts/prototype_extract_health_claims.py run-pipeline \
  --transcript data/transcripts/norm/web__the-ready-state__layne-norton__2022-10-20__v1.json \
  --models qwen3:4b \
  --query-model qwen3:4b \
  --output data/claims.jsonl \
  --queries-output data/claim_queries.jsonl
```

## Inputs and Outputs

Defaults:

- Transcript input:
  - `data/transcripts/norm/web__the-ready-state__layne-norton__2022-10-20__v1.json`
- Claims output:
  - `data/claims.jsonl`
- Query output:
  - `data/claim_queries.jsonl`
- Ollama URL:
  - `http://127.0.0.1:11434`

## Data Flow

`extract-claims`:

1. Load transcript segments.
2. Chunk transcript (`--chunk-size`, `--chunk-overlap`).
3. Prompt Ollama for strict JSON claims.
4. Normalize and deduplicate claims.
5. Assign `claim_id` and write JSONL.

`generate-queries`:

1. Load claims JSONL.
2. Chunk claims (`--query-chunk-size`, `--query-chunk-overlap`).
3. Prompt Ollama for validation queries.
4. Normalize and deduplicate query rows.
5. Add fallback heuristic queries for uncovered claims.
6. Write query JSONL.

`run-pipeline` combines both stages in sequence.

## Schema Notes

Claim types:

- `medical_risk`
- `treatment_effect`
- `nutrition_claim`
- `exercise_claim`
- `epidemiology`
- `other`

Claim row fields:

- `claim_id`
- `doc_id`
- `speaker`
- `claim_text`
- `evidence`
- `time_range_s`
- `claim_type`
- `boldness_rating`
- `model`

Query row fields:

- `claim_id`
- `query`
- `why_this_query`
- `preferred_sources`

## Prototype Characteristics

- Local prompt-based extraction (non-deterministic).
- Recall-first extraction behavior.
- Query generation includes fallback heuristics for coverage.
- Designed for rapid iteration, not production hardening.
