"""Console output helpers for prototype pipeline commands."""

from __future__ import annotations

from typing import Any

from rich.console import Console


def print_claim_rows(rows: list[dict[str, Any]], console: Console) -> None:
    """Print extracted claim rows."""
    console.print("[bold]Extracted claims[/bold]:")
    for row in rows:
        console.print(
            f"{row.get('claim_id', 'unknown')} | {row.get('model', 'unknown')} | "
            f"{row.get('speaker', 'unknown')} | {row.get('claim_type', 'unknown')} | "
            f"{row.get('claim_text', '')}"
        )


def print_query_rows(rows: list[dict[str, Any]], console: Console) -> None:
    """Print generated query rows."""
    console.print("[bold]Validation queries[/bold]:")
    for row in rows:
        console.print(
            f"{row.get('claim_id', 'unknown')} | {row.get('query', '')} | "
            f"{row.get('why_this_query', '')} | {', '.join(row.get('preferred_sources', []))}"
        )
