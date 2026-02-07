set shell := ["zsh", "-cu"]

default:
    @just --list

sync:
    uv sync

run *args:
    uv run proof-please {{args}}

init-db:
    uv run proof-please init-db

prototype transcript:
    uv run python scripts/prototype_extract_predictions.py {{transcript}}
