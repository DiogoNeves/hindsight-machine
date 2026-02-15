"""Streamlit entrypoint for data explorer workflows."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from proof_please.explorer.data_access import ExplorerDataset, load_dataset
from proof_please.explorer.linking import compute_link_diagnostics
from proof_please.explorer.styles import APP_STYLE
from proof_please.explorer.views import (
    render_claims_tab,
    render_diagnostics_tab,
    render_episode_browser,
    render_hero,
    render_queries_tab,
)

DEFAULT_CLAIMS_PATH = "data/claims.jsonl"
DEFAULT_QUERIES_PATH = "data/claim_queries.jsonl"
DEFAULT_TRANSCRIPTS_PATH = "data/transcripts/norm"


@st.cache_data(show_spinner=False)
def _load_dataset_cached(
    claims_path: str,
    queries_path: str,
    transcripts_path: str,
) -> ExplorerDataset:
    return load_dataset(
        claims_path=Path(claims_path),
        queries_path=Path(queries_path),
        transcripts_path=Path(transcripts_path),
    )


def main() -> None:
    """Run the Streamlit explorer app."""
    st.set_page_config(
        page_title="Proof, Please Explorer",
        page_icon=":mag:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(APP_STYLE, unsafe_allow_html=True)

    with st.sidebar:
        st.header("Data sources")
        claims_path = st.text_input("Claims JSONL", value=DEFAULT_CLAIMS_PATH)
        queries_path = st.text_input("Queries JSONL", value=DEFAULT_QUERIES_PATH)
        transcripts_path = st.text_input(
            "Transcript JSON or directory",
            value=DEFAULT_TRANSCRIPTS_PATH,
        )
        if st.button("Reload from disk", width="stretch"):
            _load_dataset_cached.clear()
        st.caption("Paths are resolved from the current working directory.")

    try:
        dataset = _load_dataset_cached(claims_path, queries_path, transcripts_path)
    except Exception as exc:  # noqa: BLE001 - surface readable message in app
        st.error(f"Could not load explorer dataset: {exc}")
        st.stop()

    diagnostics = compute_link_diagnostics(
        claims=dataset.claims,
        queries=dataset.queries,
        transcripts_by_doc_id=dataset.transcripts_by_doc_id,
    )

    if "pp_mode" not in st.session_state:
        st.session_state["pp_mode"] = "Episode Browser"

    st.markdown("### Explorer Mode")
    mode = st.radio(
        "Explorer Mode",
        options=["Episode Browser", "Debug Mode"],
        key="pp_mode",
        horizontal=True,
        label_visibility="collapsed",
    )

    if mode == "Episode Browser":
        render_episode_browser(dataset)
        return

    render_hero(diagnostics)
    debug_sections = ["Claims", "Queries", "Diagnostics"]
    if st.session_state.get("pp_debug_section") not in debug_sections:
        st.session_state["pp_debug_section"] = debug_sections[0]

    debug_section = st.radio(
        "Debug workflow",
        options=debug_sections,
        key="pp_debug_section",
        horizontal=True,
    )
    if debug_section == "Claims":
        render_claims_tab(dataset)
    elif debug_section == "Queries":
        render_queries_tab(dataset)
    else:
        render_diagnostics_tab(dataset, diagnostics)


if __name__ == "__main__":
    main()
