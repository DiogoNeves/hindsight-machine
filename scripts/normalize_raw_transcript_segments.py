"""Prototype converter from raw transcript JSON to segmented transcript JSON."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

SPEAKER_TIMESTAMP_RE = re.compile(
    r"^(?P<speaker>[^:\n]{1,120}):\s*(?:\[\s*|\(\s*)?"
    r"(?P<timestamp>(?:\d{1,2}:)?\d{1,2}:\d{2})(?:\s*\]|\s*\))?\s*$"
)
WHITESPACE_RE = re.compile(r"\s+")
VERSION_SUFFIX_RE = re.compile(r"__v\d+$")


def parse_args() -> argparse.Namespace:
    """Parse CLI args for prototype conversion."""
    parser = argparse.ArgumentParser(
        description="Convert raw transcript JSON files into segmented normalized JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Single raw transcript JSON file to convert.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/transcripts/raw"),
        help="Directory containing raw transcript JSON files (default: data/transcripts/raw).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/transcripts/norm"),
        help="Directory for normalized transcript JSON files (default: data/transcripts/norm).",
    )
    return parser.parse_args()


def slugify(value: str, fallback: str = "unknown") -> str:
    """Convert text into an ASCII slug."""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or fallback


def parse_timestamp_to_seconds(timestamp: str) -> int:
    """Parse mm:ss or hh:mm:ss timestamp into total seconds."""
    parts = [int(part) for part in timestamp.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported timestamp format: {timestamp}")


def normalize_segment_text(lines: list[str]) -> str:
    """Join multi-line utterances into a single normalized text block."""
    pieces = [line.strip() for line in lines if line.strip()]
    return WHITESPACE_RE.sub(" ", " ".join(pieces)).strip()


def extract_segments(raw_text: str) -> list[dict[str, Any]]:
    """Extract timestamped speaker segments from raw transcript text."""
    segments: list[dict[str, Any]] = []

    current_speaker: str | None = None
    current_start: int | None = None
    current_text_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_speaker, current_start, current_text_lines
        if current_speaker is None or current_start is None:
            return

        text = normalize_segment_text(current_text_lines)
        if text:
            segments.append(
                {
                    "seg_id": f"seg_{len(segments) + 1:06d}",
                    "speaker": current_speaker,
                    "start_time_s": current_start,
                    "text": text,
                }
            )

        current_speaker = None
        current_start = None
        current_text_lines = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        speaker_match = SPEAKER_TIMESTAMP_RE.match(line)
        if speaker_match:
            flush_current()
            current_speaker = speaker_match.group("speaker").strip()
            current_start = parse_timestamp_to_seconds(speaker_match.group("timestamp"))
            continue

        if current_speaker is not None:
            current_text_lines.append(line)

    flush_current()
    return segments


def derive_doc_id(data: dict[str, Any]) -> str:
    """Create a compact doc_id aligned with the prototype normalized format."""
    episode = data.get("episode", {})
    podcast_name = str(episode.get("podcast_name", "")).strip()
    title = str(episode.get("title", "")).strip()
    published_date = str(episode.get("published_date", "")).strip()

    if podcast_name and title and published_date:
        podcast_slug = slugify(podcast_name).replace("-", "")
        title_slug = slugify(title)
        return f"{podcast_slug}_{title_slug}_{published_date}"

    raw_doc_id = str(data.get("doc_id", "")).strip()
    if raw_doc_id:
        compact = raw_doc_id
        if compact.startswith("web__"):
            compact = compact[len("web__") :]
        compact = VERSION_SUFFIX_RE.sub("", compact)
        compact = compact.replace("__", "_")
        return compact

    return "unknown_document"


def normalize_document(data: dict[str, Any]) -> dict[str, Any]:
    """Build normalized transcript structure with `segments`."""
    raw_text = str(data.get("raw", ""))
    episode = data.get("episode", {})

    return {
        "doc_id": derive_doc_id(data),
        "source": data.get("source", {}),
        "episode": {
            "title": episode.get("title"),
            "published_date": episode.get("published_date"),
        },
        "segments": extract_segments(raw_text),
    }


def convert_file(input_path: Path, output_dir: Path) -> Path:
    """Convert a raw transcript JSON file and write normalized output."""
    with input_path.open("r", encoding="utf-8") as file:
        raw_data = json.load(file)

    normalized = normalize_document(raw_data)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / input_path.name
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(normalized, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return output_path


def collect_inputs(single_input: Path | None, input_dir: Path) -> list[Path]:
    """Resolve which input files should be converted."""
    if single_input is not None:
        return [single_input]
    return sorted(path for path in input_dir.glob("*.json") if path.is_file())


def main() -> int:
    """CLI entrypoint for prototype transcript normalization."""
    args = parse_args()
    input_files = collect_inputs(args.input, args.input_dir)

    if not input_files:
        print("No input JSON files found.")
        return 1

    for input_path in input_files:
        output_path = convert_file(input_path, args.output_dir)
        print(f"Converted {input_path} -> {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
