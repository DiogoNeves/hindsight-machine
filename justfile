set shell := ["zsh", "-cu"]

default:
    @just --list

sync:
    uv sync

run *args:
    uv run hindsight-machine {{args}}

init-db:
    uv run hindsight-machine init-db

prototype transcript:
    uv run python scripts/prototype_extract_predictions.py {{transcript}}
