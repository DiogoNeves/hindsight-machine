set shell := ["zsh", "-cu"]

default:
    @just --list

sync:
    uv sync

run *args:
    uv run proof-please {{args}}

explore-data *args:
    uv run streamlit run src/proof_please/explorer/app.py {{args}}

init-db:
    uv run proof-please init-db

extract-claims transcript:
    uv run proof-please extract-claims --transcript {{transcript}}
