"""UI rendering functions for Streamlit explorer tabs."""

from __future__ import annotations

import html
from collections import defaultdict

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
    EpisodeClaimRow,
    SourceGroup,
    claim_matches_filters,
    build_claims_to_queries_index,
    build_episode_claim_rows,
    build_segment_to_claims_index,
    build_source_episode_index,
    build_source_summary,
    default_claim_for_segment,
    episode_option_label,
    filter_episode_claim_rows,
    query_matches_filters,
    truncate_preview,
)
from proof_please.pipeline.models import TranscriptDocument, TranscriptSegment


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


def _format_timestamp(seconds: int) -> str:
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _segment_option_label(segment: TranscriptSegment) -> str:
    preview = truncate_preview(segment.text, limit=82)
    return (
        f"{segment.seg_id} | {_format_timestamp(segment.start_time_s)} | "
        f"{segment.speaker or 'Unknown speaker'} | {preview}"
    )


def _sync_select_state(key: str, options: list[str]) -> None:
    if not options:
        st.session_state.pop(key, None)
        return
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]


def _sanitize_multiselect_state(key: str, options: list[str]) -> None:
    selected = st.session_state.get(key, [])
    if not isinstance(selected, list):
        st.session_state[key] = []
        return
    sanitized = [value for value in selected if value in options]
    if sanitized != selected:
        st.session_state[key] = sanitized


def _source_group_label(group: SourceGroup) -> str:
    suffix = "episode" if len(group.episode_doc_ids) == 1 else "episodes"
    return f"{group.source_label} ({len(group.episode_doc_ids)} {suffix})"


def _episode_claim_row_label(row: EpisodeClaimRow) -> str:
    speaker = row.speaker or "Unknown speaker"
    preview = truncate_preview(row.claim_text)
    return f"{row.claim_id} | {speaker} | {preview}"


def _set_claim_debug_state(claim: ClaimRow) -> None:
    st.session_state["pp_mode"] = "Debug Mode"
    st.session_state["pp_debug_section"] = "Claims"
    st.session_state["claims_doc_filter"] = claim.doc_id
    st.session_state["claims_search"] = ""
    st.session_state["claims_speaker_filter"] = []
    st.session_state["claims_type_filter"] = []
    st.session_state["claims_model_filter"] = []
    st.session_state["claims_with_queries_filter"] = False
    st.session_state["claims_selected_claim"] = claim.claim_id
    st.session_state["claims_focus_claim_id"] = claim.claim_id


def _set_query_debug_state(claim: ClaimRow) -> None:
    st.session_state["pp_mode"] = "Debug Mode"
    st.session_state["pp_debug_section"] = "Queries"
    st.session_state["queries_focus_claim_id"] = claim.claim_id
    st.session_state["queries_search"] = ""
    st.session_state["queries_source_filter"] = []
    st.session_state["queries_claim_type_filter"] = []
    st.session_state["queries_orphan_filter"] = False
    st.session_state["queries_selected_query"] = 0


def render_source_summary(
    group: SourceGroup,
    summary_claim_count: int,
    summary_query_count: int,
    top_speakers: tuple[str, ...],
) -> None:
    """Render a lightweight source-level summary."""
    st.markdown("#### Source summary")
    col1, col2 = st.columns(2)
    col1.metric("Episodes", len(group.episode_doc_ids))
    col2.metric("Claims", summary_claim_count)
    col3, col4 = st.columns(2)
    col3.metric("Queries", summary_query_count)
    col4.metric("Top speakers", len(top_speakers))

    if top_speakers:
        st.caption(f"Top speakers: {', '.join(top_speakers)}")


def render_episode_claim_overview(rows: list[EpisodeClaimRow]) -> None:
    """Render compact claim overview table for selected episode."""
    st.markdown("#### Episode claims")
    if not rows:
        st.info("No claims match the selected episode filters.")
        return

    table_rows = [
        {
            "claim_id": row.claim_id,
            "speaker": row.speaker or "Unknown",
            "type": row.claim_type,
            "queries": row.query_count,
            "claim_text": truncate_preview(row.claim_text, limit=86),
        }
        for row in rows
    ]
    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        height=min(360, 46 + 34 * len(table_rows)),
    )


def render_transcript_with_highlights(
    document: TranscriptDocument,
    *,
    highlighted_claim_counts: dict[str, int],
    active_seg_id: str,
    search_text: str,
) -> None:
    """Render the full transcript with claim-highlighted segment rows."""
    normalized_search = search_text.strip().lower()
    for segment in document.segments:
        claim_count = highlighted_claim_counts.get(segment.seg_id, 0)
        classes = ["segment-row"]
        if claim_count > 0:
            classes.append("segment-row--claimed")
        if segment.seg_id == active_seg_id:
            classes.append("segment-row--active")
        if normalized_search and normalized_search in segment.text.lower():
            classes.append("segment-row--match")

        claim_badge = ""
        if claim_count > 0:
            suffix = "claim" if claim_count == 1 else "claims"
            claim_badge = f"<span class='segment-badge'>{claim_count} {suffix}</span>"

        st.markdown(
            (
                f"<article class='{' '.join(classes)}'>"
                "<div class='segment-row-meta'>"
                f"<span class='segment-seg-id'>{html.escape(segment.seg_id)}</span>"
                f"<span>{_format_timestamp(segment.start_time_s)}</span>"
                f"<span>{html.escape(segment.speaker or 'Unknown speaker')}</span>"
                f"{claim_badge}"
                "</div>"
                f"<p class='segment-row-text'>{html.escape(segment.text)}</p>"
                "</article>"
            ),
            unsafe_allow_html=True,
        )


def render_segment_inspector(
    *,
    document: TranscriptDocument,
    active_segment: TranscriptSegment,
    linked_claims: list[ClaimRow],
    hidden_claim_count: int,
    queries_by_claim_id: dict[str, list[QueryRow]],
) -> None:
    """Render right-panel inspector for active transcript segment."""
    st.markdown("### Segment inspector")
    st.markdown(
        (
            "<div class='card-shell'>"
            "<p class='meta-note'>"
            f"{html.escape(active_segment.seg_id)} | {_format_timestamp(active_segment.start_time_s)} | "
            f"{html.escape(active_segment.speaker or 'Unknown speaker')}"
            "</p>"
            f"<p class='claim-line'>{html.escape(active_segment.text)}</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if not linked_claims:
        st.info("No claim links for this segment under current filters.")
        if hidden_claim_count > 0:
            st.caption(f"{hidden_claim_count} claim link(s) hidden by the current filters.")
        return

    claim_ids = [claim.claim_id for claim in linked_claims]
    default_claim = default_claim_for_segment(linked_claims)
    if st.session_state.get("episode_active_claim_id") not in claim_ids:
        st.session_state["episode_active_claim_id"] = (
            default_claim.claim_id if default_claim else claim_ids[0]
        )

    claim_lookup = {claim.claim_id: claim for claim in linked_claims}
    selected_claim_id = st.selectbox(
        "Linked claims on this segment",
        options=claim_ids,
        format_func=lambda claim_id: _claim_label(claim_lookup[claim_id]),
        key="episode_active_claim_id",
    )
    selected_claim = claim_lookup[selected_claim_id]

    st.markdown("#### Claim detail")
    _render_claim_card(selected_claim)

    linked_queries = queries_by_claim_id.get(selected_claim.claim_id, [])
    st.markdown("#### Linked queries")
    st.caption(f"{len(linked_queries)} linked queries")
    if not linked_queries:
        st.info("No queries linked to this claim.")
    for index, query in enumerate(linked_queries, start=1):
        with st.expander(f"Query {index}: {query.query}", expanded=False):
            if query.why_this_query:
                st.write(query.why_this_query)
            if query.preferred_sources:
                st.caption(f"Preferred sources: {', '.join(query.preferred_sources)}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Open in Claims debug",
            key=f"open_claim_debug_{document.doc_id}_{selected_claim.claim_id}",
            width="stretch",
        ):
            _set_claim_debug_state(selected_claim)
            st.rerun()
    with col2:
        if st.button(
            "Open in Queries debug",
            key=f"open_query_debug_{document.doc_id}_{selected_claim.claim_id}",
            width="stretch",
        ):
            _set_query_debug_state(selected_claim)
            st.rerun()


def render_episode_browser(dataset: ExplorerDataset) -> None:
    """Render source/episode-first transcript browsing workflow."""
    st.markdown("## Episode Browser")
    st.caption("Start from source and episode, browse transcript highlights, inspect linked claims and queries.")

    if not dataset.transcripts_by_doc_id:
        st.info("No transcript documents loaded. Add transcript JSON files to browse episodes.")
        return

    queries_by_claim_id = build_claims_to_queries_index(dataset.queries)
    segment_to_claims = build_segment_to_claims_index(dataset.claims)
    source_groups, episodes_by_doc_id = build_source_episode_index(
        dataset.transcripts_by_doc_id,
        dataset.claims,
        dataset.queries,
    )
    if not source_groups:
        st.info("No source groups available for the currently loaded transcripts.")
        return

    source_keys = [group.source_key for group in source_groups]
    _sync_select_state("episode_source_key", source_keys)
    source_lookup = {group.source_key: group for group in source_groups}

    selected_source_key = st.session_state["episode_source_key"]
    selected_source = source_lookup[selected_source_key]
    episode_doc_ids = list(selected_source.episode_doc_ids)
    _sync_select_state("episode_doc_id", episode_doc_ids)

    selected_doc_id = st.session_state["episode_doc_id"]
    selected_document = dataset.transcripts_by_doc_id[selected_doc_id]

    queries_by_claim_id = build_claims_to_queries_index(dataset.queries)
    source_summary = build_source_summary(
        selected_source.episode_doc_ids,
        dataset.claims,
        queries_by_claim_id,
    )

    episode_rows = build_episode_claim_rows(
        selected_doc_id,
        dataset.claims,
        queries_by_claim_id,
    )
    speaker_options = sorted({row.speaker for row in episode_rows if row.speaker})
    claim_type_options = sorted({row.claim_type for row in episode_rows if row.claim_type})
    _sanitize_multiselect_state("episode_speaker_filter", speaker_options)
    _sanitize_multiselect_state("episode_claim_type_filter", claim_type_options)

    left, center, right = st.columns([1.05, 1.5, 1.15], gap="large")

    with left:
        st.selectbox(
            "Source",
            options=source_keys,
            format_func=lambda source_key: _source_group_label(source_lookup[source_key]),
            key="episode_source_key",
        )

        selected_source = source_lookup[st.session_state["episode_source_key"]]
        episode_doc_ids = list(selected_source.episode_doc_ids)
        _sync_select_state("episode_doc_id", episode_doc_ids)

        st.selectbox(
            "Episode",
            options=episode_doc_ids,
            format_func=lambda doc_id: episode_option_label(episodes_by_doc_id[doc_id]),
            key="episode_doc_id",
        )

        selected_doc_id = st.session_state["episode_doc_id"]
        selected_document = dataset.transcripts_by_doc_id[selected_doc_id]
        episode_rows = build_episode_claim_rows(
            selected_doc_id,
            dataset.claims,
            queries_by_claim_id,
        )
        speaker_options = sorted({row.speaker for row in episode_rows if row.speaker})
        claim_type_options = sorted({row.claim_type for row in episode_rows if row.claim_type})
        _sanitize_multiselect_state("episode_speaker_filter", speaker_options)
        _sanitize_multiselect_state("episode_claim_type_filter", claim_type_options)

        render_source_summary(
            selected_source,
            summary_claim_count=source_summary.claim_count,
            summary_query_count=source_summary.query_count,
            top_speakers=source_summary.top_speakers,
        )

        st.markdown("#### Claim filters")
        selected_speakers = st.multiselect(
            "Speakers",
            options=speaker_options,
            key="episode_speaker_filter",
        )
        selected_claim_types = st.multiselect(
            "Claim types",
            options=claim_type_options,
            key="episode_claim_type_filter",
        )
        only_with_queries = st.checkbox(
            "Only claims with linked queries",
            value=False,
            key="episode_only_with_queries",
        )
        claim_search_text = st.text_input(
            "Search claims",
            key="episode_claim_search",
        )

        filtered_rows = filter_episode_claim_rows(
            episode_rows,
            selected_speakers=selected_speakers,
            selected_claim_types=selected_claim_types,
            only_with_queries=only_with_queries,
            search_text=claim_search_text,
        )
        st.caption(f"Showing {len(filtered_rows)} of {len(episode_rows)} claims.")
        render_episode_claim_overview(filtered_rows)

        jump_rows = [row for row in filtered_rows if row.first_seg_id]
        if jump_rows:
            jump_claim_ids = [row.claim_id for row in jump_rows]
            _sync_select_state("episode_jump_claim_id", jump_claim_ids)
            jump_lookup = {row.claim_id: row for row in jump_rows}
            st.selectbox(
                "Jump to claim evidence",
                options=jump_claim_ids,
                format_func=lambda claim_id: _episode_claim_row_label(jump_lookup[claim_id]),
                key="episode_jump_claim_id",
            )
            if st.button("Jump to evidence segment", key="episode_jump_to_claim_button", width="stretch"):
                selected_jump = jump_lookup[st.session_state["episode_jump_claim_id"]]
                st.session_state["episode_active_seg_id"] = selected_jump.first_seg_id
                st.session_state["episode_active_claim_id"] = selected_jump.claim_id
                st.rerun()
        else:
            st.caption("No claim jump targets available for the current filters.")

    filtered_claim_id_set = {row.claim_id for row in filtered_rows}
    segment_claims_for_doc: dict[str, list[ClaimRow]] = defaultdict(list)
    for (doc_id, seg_id), claim_rows in segment_to_claims.items():
        if doc_id != selected_doc_id:
            continue
        segment_claims_for_doc[seg_id] = [
            row for row in claim_rows if row.claim_id in filtered_claim_id_set
        ]

    segment_lookup = {segment.seg_id: segment for segment in selected_document.segments}
    segment_ids = list(segment_lookup.keys())
    if not segment_ids:
        with center:
            st.info("Selected episode has no transcript segments.")
        with right:
            st.info("Select another episode to inspect linked claim evidence.")
        return

    _sync_select_state("episode_active_seg_id", segment_ids)
    active_seg_id = st.session_state["episode_active_seg_id"]
    active_segment = segment_lookup[active_seg_id]

    with center:
        st.markdown("### Transcript")
        transcript_search_text = st.text_input(
            "Search transcript text",
            key="episode_transcript_search",
        )

        if transcript_search_text.strip():
            matching_segment_ids = [
                segment.seg_id
                for segment in selected_document.segments
                if transcript_search_text.strip().lower() in segment.text.lower()
            ]
            if matching_segment_ids:
                _sync_select_state("episode_match_seg_id", matching_segment_ids)
                st.selectbox(
                    "Jump to text match",
                    options=matching_segment_ids,
                    format_func=lambda seg_id: _segment_option_label(segment_lookup[seg_id]),
                    key="episode_match_seg_id",
                )
                if st.button("Go to match", key="episode_go_match", width="content"):
                    st.session_state["episode_active_seg_id"] = st.session_state["episode_match_seg_id"]
                    st.rerun()
                st.caption(f"{len(matching_segment_ids)} matching segment(s).")
            else:
                st.caption("No matching transcript segments found for the current search.")

        st.selectbox(
            "Active segment",
            options=segment_ids,
            format_func=lambda seg_id: _segment_option_label(segment_lookup[seg_id]),
            key="episode_active_seg_id",
        )

        highlighted_claim_counts = {
            seg_id: len(claim_rows)
            for seg_id, claim_rows in segment_claims_for_doc.items()
            if claim_rows
        }
        render_transcript_with_highlights(
            selected_document,
            highlighted_claim_counts=highlighted_claim_counts,
            active_seg_id=st.session_state["episode_active_seg_id"],
            search_text=transcript_search_text,
        )

    all_linked_claims = segment_to_claims.get((selected_doc_id, active_segment.seg_id), [])
    visible_linked_claims = [
        row for row in all_linked_claims if row.claim_id in filtered_claim_id_set
    ]
    hidden_claim_count = len(all_linked_claims) - len(visible_linked_claims)
    with right:
        render_segment_inspector(
            document=selected_document,
            active_segment=active_segment,
            linked_claims=visible_linked_claims,
            hidden_claim_count=hidden_claim_count,
            queries_by_claim_id=queries_by_claim_id,
        )


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
    focus_claim_id = st.session_state.pop("claims_focus_claim_id", "")
    if focus_claim_id and focus_claim_id in claim_lookup:
        st.session_state["claims_selected_claim"] = focus_claim_id
    claim_ids = list(claim_lookup.keys())
    if st.session_state.get("claims_selected_claim") not in claim_ids:
        st.session_state["claims_selected_claim"] = claim_ids[0]

    selected_claim_id = st.selectbox(
        "Select claim",
        options=claim_ids,
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

    focus_claim_id = st.session_state.pop("queries_focus_claim_id", "")
    if focus_claim_id:
        focused_queries = [query for query in filtered_queries if query.claim_id == focus_claim_id]
        if focused_queries:
            filtered_queries = focused_queries

    st.caption(f"Showing {len(filtered_queries)} of {len(queries)} queries.")
    if not filtered_queries:
        st.info("No queries match the current filters.")
        return

    query_indices = list(range(len(filtered_queries)))
    if st.session_state.get("queries_selected_query") not in query_indices:
        st.session_state["queries_selected_query"] = query_indices[0]

    selected_query_index = st.selectbox(
        "Select query",
        options=query_indices,
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
