"""UI rendering functions for Streamlit explorer tabs."""

from __future__ import annotations

import html

import streamlit as st

from proof_please.explorer.data_access import ExplorerDataset
from proof_please.explorer.linking import (
    LinkDiagnostics,
    group_queries_by_claim_id,
    index_claims_by_id,
    resolve_claim_evidence,
)
from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.explorer.view_logic import (
    claim_matches_filters,
    query_matches_filters,
    truncate_preview,
)


def _render_text_card(text: str) -> None:
    st.markdown(
        (
            "<div class='card-shell'>"
            f"<p class='claim-line'>{html.escape(text)}</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _claim_label(claim: ClaimRow) -> str:
    preview = truncate_preview(claim.claim_text)
    speaker = claim.speaker or "Unknown speaker"
    return f"{claim.claim_id} | {speaker} | {preview}"


def _query_label(query: QueryRow) -> str:
    preview = truncate_preview(query.query)
    return f"{query.claim_id} | {preview}"


def render_hero(diagnostics: LinkDiagnostics) -> None:
    """Render the top app hero section."""
    st.markdown(
        (
            "<section class='hero'>"
            "<p class='hero-kicker'>Proof, Please - Data Explorer</p>"
            "<h1>Trace each claim back to transcript evidence and forward to validation queries</h1>"
            "<p class='hero-subtext'>"
            f"{diagnostics.total_claims} claims, {diagnostics.total_queries} queries, and "
            f"{diagnostics.total_transcript_docs} transcript docs loaded for debugging."
            "</p>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def _render_claim_card(claim: ClaimRow) -> None:
    _render_text_card(claim.claim_text)
    time_start = claim.time_range_s.get("start")
    time_end = claim.time_range_s.get("end")
    time_text = ""
    if time_start is not None and time_end is not None:
        time_text = f" | range {time_start}s-{time_end}s"
    elif time_start is not None:
        time_text = f" | start {time_start}s"
    st.caption(
        (
            f"`{claim.claim_id}` | doc `{claim.doc_id}` | speaker `{claim.speaker or 'unknown'}`"
            f" | type `{claim.claim_type}` | model `{claim.model or 'unknown'}`{time_text}"
        )
    )


def _render_claim_evidence(claim: ClaimRow, dataset: ExplorerDataset, expander_prefix: str) -> None:
    resolved_rows = resolve_claim_evidence(claim, dataset.transcripts_by_doc_id)
    if not resolved_rows:
        st.info("No evidence rows available for this claim.")
        return

    for index, resolved in enumerate(resolved_rows, start=1):
        status = "matched" if resolved.found else "missing segment"
        label = f"{expander_prefix} {index}: {resolved.seg_id} ({status})"
        with st.expander(label, expanded=not resolved.found):
            if resolved.quote:
                st.markdown(f"**Claim quote**\n\n> {resolved.quote}")
            if resolved.found:
                st.markdown(
                    f"<p class='meta-note'>{resolved.speaker or 'Unknown speaker'} | "
                    f"{resolved.start_time_s}s</p>",
                    unsafe_allow_html=True,
                )
                st.write(resolved.segment_text)
            else:
                st.error(
                    "Transcript segment not found for this seg_id in the linked document. "
                    "Check transcript normalization and claim evidence ids."
                )


def render_claims_tab(dataset: ExplorerDataset) -> None:
    """Render claims-first workflow with transcript and query linkage."""
    st.subheader("Claims -> Transcript -> Queries")
    claims = sorted(dataset.claims, key=lambda row: row.claim_id)
    queries_by_claim_id = group_queries_by_claim_id(dataset.queries)

    if not claims:
        st.info("No claims loaded. Check your claims JSONL path.")
        return

    docs = sorted({claim.doc_id for claim in claims})
    speakers = sorted({claim.speaker for claim in claims if claim.speaker})
    claim_types = sorted({claim.claim_type for claim in claims if claim.claim_type})
    models = sorted({claim.model for claim in claims if claim.model})

    with st.container():
        col1, col2, col3, col4 = st.columns(4)
        search_text = col1.text_input("Search claims", key="claims_search")
        selected_doc = col2.selectbox("Document", options=["All", *docs], key="claims_doc_filter")
        selected_speakers = col3.multiselect("Speakers", options=speakers, key="claims_speaker_filter")
        selected_claim_types = col4.multiselect(
            "Claim types",
            options=claim_types,
            key="claims_type_filter",
        )

        col5, col6 = st.columns(2)
        selected_models = col5.multiselect("Models", options=models, key="claims_model_filter")
        only_with_queries = col6.checkbox(
            "Only claims with linked queries",
            value=False,
            key="claims_with_queries_filter",
        )

    search_text = search_text.strip().lower()
    filtered_claims = [
        claim
        for claim in claims
        if claim_matches_filters(
            claim,
            selected_doc=selected_doc,
            selected_speakers=selected_speakers,
            selected_claim_types=selected_claim_types,
            selected_models=selected_models,
            only_with_queries=only_with_queries,
            queries_by_claim_id=queries_by_claim_id,
            search_text=search_text,
        )
    ]

    st.caption(f"Showing {len(filtered_claims)} of {len(claims)} claims.")
    if not filtered_claims:
        st.info("No claims match the current filters.")
        return

    claim_lookup = {claim.claim_id: claim for claim in filtered_claims}
    selected_claim_id = st.selectbox(
        "Select claim",
        options=list(claim_lookup.keys()),
        format_func=lambda claim_id: _claim_label(claim_lookup[claim_id]),
        key="claims_selected_claim",
    )
    selected_claim = claim_lookup[selected_claim_id]

    left, right = st.columns([1.25, 1.0], gap="large")

    with left:
        st.markdown("#### Claim detail")
        _render_claim_card(selected_claim)
        st.markdown("#### Linked transcript segments")
        _render_claim_evidence(selected_claim, dataset, expander_prefix="Evidence")

    linked_queries = queries_by_claim_id.get(selected_claim.claim_id, [])
    with right:
        st.markdown("#### Query preview")
        st.caption(f"{len(linked_queries)} linked queries")
        if not linked_queries:
            st.info("No query rows linked to this claim_id yet.")
        for index, query in enumerate(linked_queries, start=1):
            with st.expander(f"Query {index}: {query.query}"):
                st.markdown(f"**Claim ID**: `{query.claim_id}`")
                if query.why_this_query:
                    st.write(query.why_this_query)
                if query.preferred_sources:
                    st.caption(
                        "Preferred sources: "
                        f"{', '.join(query.preferred_sources)}"
                    )


def render_queries_tab(dataset: ExplorerDataset) -> None:
    """Render query-first workflow with claim and transcript back-links."""
    st.subheader("Queries -> Claims -> Transcript evidence")
    queries = dataset.queries
    claim_index = index_claims_by_id(dataset.claims)
    if not queries:
        st.info("No query rows loaded. Check your query JSONL path.")
        return

    available_sources = sorted(
        {
            source
            for query in queries
            for source in query.preferred_sources
            if source
        }
    )
    claim_type_options = sorted(
        {
            claim.claim_type
            for claim in claim_index.values()
            if claim.claim_type
        }
    )

    with st.container():
        col1, col2, col3, col4 = st.columns(4)
        search_text = col1.text_input("Search queries", key="queries_search")
        selected_sources = col2.multiselect(
            "Preferred sources",
            options=available_sources,
            key="queries_source_filter",
        )
        selected_claim_types = col3.multiselect(
            "Linked claim type",
            options=claim_type_options,
            key="queries_claim_type_filter",
        )
        only_orphans = col4.checkbox("Only orphan queries", value=False, key="queries_orphan_filter")

    selected_source_set = set(selected_sources)
    search_text = search_text.strip().lower()
    filtered_queries = [
        query
        for query in queries
        if query_matches_filters(
            query,
            linked_claim=claim_index.get(query.claim_id),
            selected_claim_types=selected_claim_types,
            selected_source_set=selected_source_set,
            only_orphans=only_orphans,
            search_text=search_text,
        )
    ]

    st.caption(f"Showing {len(filtered_queries)} of {len(queries)} queries.")
    if not filtered_queries:
        st.info("No queries match the current filters.")
        return

    selected_query_index = st.selectbox(
        "Select query",
        options=list(range(len(filtered_queries))),
        format_func=lambda index: _query_label(filtered_queries[index]),
        key="queries_selected_query",
    )
    selected_query = filtered_queries[selected_query_index]
    linked_claim = claim_index.get(selected_query.claim_id)

    left, right = st.columns([1.05, 1.2], gap="large")
    with left:
        st.markdown("#### Query detail")
        _render_text_card(selected_query.query)
        st.caption(f"Linked claim id: `{selected_query.claim_id}`")
        if selected_query.why_this_query:
            st.write(selected_query.why_this_query)
        if selected_query.preferred_sources:
            st.caption(f"Preferred sources: {', '.join(selected_query.preferred_sources)}")

    with right:
        st.markdown("#### Linked claim")
        if linked_claim is None:
            st.error(
                "This query points to a claim_id that is not present in the claims artifact. "
                "Use Diagnostics to inspect all orphan queries."
            )
        else:
            _render_claim_card(linked_claim)
            st.markdown("#### Claim transcript evidence")
            _render_claim_evidence(linked_claim, dataset, expander_prefix="Transcript evidence")


def _render_issues(title: str, rows: list[dict[str, str]], empty_message: str) -> None:
    with st.expander(title, expanded=False):
        if not rows:
            st.success(empty_message)
            return
        st.dataframe(rows, use_container_width=True)


def render_diagnostics_tab(dataset: ExplorerDataset, diagnostics: LinkDiagnostics) -> None:
    """Render coverage and broken-link diagnostics for loaded data."""
    st.subheader("Link diagnostics")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Orphan queries", len(diagnostics.orphan_queries))
    col2.metric("Claims w/o queries", len(diagnostics.claims_without_queries))
    col3.metric("Claims missing transcript", len(diagnostics.claims_missing_transcript_doc))
    col4.metric("Missing evidence links", len(diagnostics.missing_evidence_links))

    if dataset.warnings:
        with st.expander("Load warnings", expanded=False):
            for warning in dataset.warnings:
                st.warning(warning)

    _render_issues(
        title="Orphan queries",
        rows=[
            {"claim_id": row.claim_id, "query": row.query}
            for row in diagnostics.orphan_queries
        ],
        empty_message="Every query row resolves to a known claim.",
    )

    _render_issues(
        title="Claims without generated queries",
        rows=[
            {
                "claim_id": row.claim_id,
                "doc_id": row.doc_id,
                "claim_text": row.claim_text,
            }
            for row in diagnostics.claims_without_queries
        ],
        empty_message="Every claim has at least one linked query.",
    )

    _render_issues(
        title="Claims pointing to missing transcript docs",
        rows=[
            {
                "claim_id": row.claim_id,
                "doc_id": row.doc_id,
                "claim_text": row.claim_text,
            }
            for row in diagnostics.claims_missing_transcript_doc
        ],
        empty_message="Every claim doc_id is present in the transcript artifact set.",
    )

    _render_issues(
        title="Claims missing evidence rows",
        rows=[
            {
                "claim_id": row.claim_id,
                "doc_id": row.doc_id,
                "claim_text": row.claim_text,
            }
            for row in diagnostics.claims_without_evidence
        ],
        empty_message="Every claim has at least one evidence item.",
    )

    _render_issues(
        title="Evidence seg_ids not found in linked transcript",
        rows=[
            {
                "claim_id": row.claim_id,
                "doc_id": row.doc_id,
                "seg_id": row.seg_id,
                "quote": row.quote,
            }
            for row in diagnostics.missing_evidence_links
        ],
        empty_message="Every evidence seg_id resolves to a transcript segment.",
    )
