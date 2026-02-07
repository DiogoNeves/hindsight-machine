"""CLI entrypoints for hindsight-machine."""

from pathlib import Path

import typer
from rich.console import Console

from hindsight_machine.config import AppConfig
from hindsight_machine.db import get_connection, init_schema

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("config")
def show_config() -> None:
    """Print the current app configuration."""
    cfg = AppConfig()
    console.print(f"[bold]DuckDB path:[/bold] {cfg.duckdb_path}")


@app.command("prototype")
def run_prototype(transcript: Path) -> None:
    """
    Placeholder command for running the prediction extraction prototype.

    Implementation is intentionally deferred.
    """
    if not transcript.exists():
        raise typer.BadParameter(f"Transcript path does not exist: {transcript}")
    console.print(
        "[yellow]Prototype extractor not implemented yet.[/yellow]\n"
        f"Target transcript: {transcript}"
    )


@app.command("init-db")
def initialize_database() -> None:
    """Create the initial DuckDB database and schema."""
    cfg = AppConfig()
    with get_connection(cfg.duckdb_path) as conn:
        init_schema(conn)
    console.print(f"[green]Initialized DuckDB:[/green] {cfg.duckdb_path}")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
