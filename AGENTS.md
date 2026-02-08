# Repository Guidelines

## Project Structure & Module Organization
Core package code lives in `src/proof_please/`:
- `cli.py` contains Typer commands (`config`, `init-db`, `extract-claims`).
- `config.py` defines runtime settings via `pydantic-settings`.
- `db.py` manages DuckDB connection and schema bootstrap.
- `models.py` holds domain models (for example, `HealthClaim`).

Utility experiments live in `scripts/` (currently `prototype_extract_health_claims.py`). Runtime artifacts are stored in `data/` (default DB path: `data/proof_please.duckdb`).

## Build, Test, and Development Commands
- `uv sync` or `just sync`: install and lock project dependencies.
- `uv add <package>`: add new dependencies and update the lockfile.
- `just run config`: print active app configuration.
- `just init-db`: create/update the local DuckDB schema.
- `just extract-claims path/to/transcript.txt`: run health-claim extractor scaffold.
- `uv run proof-please --help`: view all CLI commands.

## Coding Style & Naming Conventions
Use Python 3.11+ conventions with 4-space indentation and explicit type hints on public functions. Keep modules focused and small, and follow existing naming patterns:
- modules/functions: `snake_case`
- classes: `PascalCase`
- constants/env vars: `UPPER_SNAKE_CASE` (for example `PP_DUCKDB_PATH`)

Prefer concise docstrings (current codebase uses them consistently) and avoid adding new dependencies unless required.

## Testing Guidelines
There is no committed test suite yet. For new features, add `pytest` tests under `tests/` mirroring the source layout (for example `tests/test_db.py`). Focus first on deterministic logic in `db.py`, `config.py`, and CLI argument validation. Run tests with `uv run pytest` once tests are present.

## Iterative Development Expectations
This project is experimental, so build in small, reversible steps and adapt as the problem becomes clearer. Do not invent roadmap details or assume future requirements; document unknowns explicitly.

When collaborating (human or AI), ask clarifying questions when requirements are ambiguous. Work from a Staff Engineer perspective: explain tradeoffs, suggest pragmatic alternatives, and prioritize solutions that keep learning velocity high.

## Commit & Pull Request Guidelines
Current history is minimal (`Initial commit`), so keep commit messages short, imperative, and descriptive (for example `Add DuckDB schema migration guard`).

For PRs, include:
- a brief summary of behavior changes
- linked issue/task ID when available
- verification steps/commands run locally
- sample CLI output when user-visible behavior changes

## Configuration & Data Notes
Settings load from environment and `.env` with prefix `PP_`. Keep local database files in `data/` and do not commit generated DB contents.
