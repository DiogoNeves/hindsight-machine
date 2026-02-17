# Streamlit Explorer

The Streamlit app is the interactive surface for browsing transcript-derived claims and linked query artifacts.

## Product Intent

Primary workflow:
- Start by source and episode.
- Read transcript content with claim-aware highlights.
- Inspect linked claims and queries without leaving transcript context.

Secondary workflow:
- Use Debug Mode tabs (`Claims`, `Queries`, `Diagnostics`) for data QA, linkage troubleshooting, and artifact validation.

The app is meant to support:
- editorial/research review of many claims in the same episode
- fast navigation between transcript segments, claims, and generated queries
- deterministic inspection when artifacts are incomplete or noisy

## Role in the Broader Roadmap

The current Streamlit app is an interim inspection tool while ingestion and extraction quality are still being tuned. Its immediate value is helping calibrate prompts and normalization logic by making errors in claim extraction, claim clustering, and transcript linkage obvious during manual review.

As ingestion scales to many podcasts, this app should continue to function as a QA/debug surface even if a different end-user UI is adopted later.

## Run Locally

```bash
just explore-data
# or
uv run streamlit run src/proof_please/explorer/app.py
```

Default artifact paths:
- claims: `data/claims.jsonl`
- queries: `data/claim_queries.jsonl`
- transcripts: `data/transcripts/norm/`

## Current UX Contract

- Default mode is `Episode Browser`.
- `Debug Mode` preserves existing claim/query/diagnostic troubleshooting flows.
- Cross-mode navigation should use Streamlit session state only (no mutation of loaded artifacts).

## Architecture Boundaries

Keep rubric-aligned separation:
- deterministic view-model shaping: `src/proof_please/explorer/view_logic.py`
- Streamlit rendering and interaction side effects: `src/proof_please/explorer/views.py`
- app-level orchestration and mode switching: `src/proof_please/explorer/app.py`
- artifact parsing/loading boundaries: `src/proof_please/explorer/models.py`, `src/proof_please/explorer/data_access.py`

When adding features:
- prefer pure helper functions for new selection/filter/index behavior
- keep UI callbacks thin and state-driven
- avoid schema or dependency changes unless explicitly required
