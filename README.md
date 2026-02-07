# Proof, Please

Proof, Please is an experimental lab for checking health claims made in podcast transcripts and grounding those claims in peer-reviewed evidence.

The core idea is simple: extract concrete claims from transcript text, query scientific literature, and summarize where research consensus appears to be strong, mixed, or unclear.

## Current Scope

- Parse and validate podcast transcript inputs.
- Bootstrap local storage in DuckDB for extracted items.
- Prototype claim extraction workflows.
- Prepare integration with the Consensus AI API for evidence retrieval.

## Consensus API

This project is designed to use the Consensus API to fetch relevant papers and metadata for each claim:

- Product page: `https://consensus.app/home/api/`
- API docs: `https://docs.consensus.app/reference/v1_quick_search`
- Current reference endpoint: `GET https://api.consensus.app/v1/quick_search`

Note: Consensus API access is application-based, so you may need approved access before live calls are possible.

## Setup

```bash
uv sync
```

## Local Commands

```bash
just sync
just init-db
just run config
just prototype path/to/transcript.txt
uv run proof-please --help
```

## Configuration

- Environment variables use the `PP_` prefix.
- Default database path is `data/proof_please.duckdb`.

## Development Approach

This repository is intentionally iterative and experimental. Expect small, reversible changes as the problem definition improves with real transcripts and evidence-review feedback.
