#!/usr/bin/env python3
"""Fetch transcript content from a URL and write normalized JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag


TIMESTAMP_RE = re.compile(r"(?:\[\s*|\(\s*)?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*\]|\s*\))?")
WHITESPACE_RE = re.compile(r"\s+")
SPEAKER_TIMESTAMP_LINE_RE = re.compile(
    r"^[^:\n]{1,80}:\s*(?:\[\s*|\(\s*)?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*\]|\s*\))?(?:\s|$)"
)
TIMESTAMP_ONLY_LINE_RE = re.compile(
    r"^(?:\[\s*|\(\s*)?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s*\]|\s*\))?$"
)

NOISE_EXACT = {
    "skip to content",
    "menu",
    "share",
    "tweet",
    "facebook",
    "x",
    "instagram",
    "linkedin",
    "youtube",
}

NOISE_PREFIXES = (
    "cookie",
    "privacy policy",
    "terms",
    "all rights reserved",
    "subscribe",
    "sign up",
    "advertisement",
    "sponsored",
)

REMOVAL_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "form",
    "iframe",
    "header",
    "footer",
    "nav",
    ".advertisement",
    ".ads",
    "#comments",
    ".social-share",
    ".share-buttons",
)

TAIL_CUTOFF_MARKERS = (
    "we use cookies to improve your experience",
    "privacy and cookie policy",
    "terms of use",
    "copyright",
    "member dashboard",
    "discussion forum",
    "hero discounts",
    "download the app",
    "join our newsletter",
    "open live chat",
)

TAIL_CUTOFF_EXACT_LINES = (
    "explore",
    "mobility challenges",
    "live q&as with kelly",
    "upcoming events",
    "pain protocols",
    "professional courses",
    "mobility gear",
    "join our newsletter",
)

CANDIDATE_SELECTORS = (
    "[itemprop='transcript']",
    "#transcript",
    ".transcript",
    "[id*='transcript']",
    "[class*='transcript']",
    ".entry-content",
    ".post-content",
    ".article-content",
    "article",
    "main",
    "body",
)

DATE_CANDIDATE_KEYS = (
    "datePublished",
    "uploadDate",
    "dateCreated",
    "dateModified",
)

TITLE_CANDIDATE_KEYS = (
    "headline",
    "name",
)


class TranscriptExtractionError(RuntimeError):
    """Raised when transcript extraction fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a transcript page and write normalized JSON output."
    )
    parser.add_argument("url", help="Transcript page URL")
    parser.add_argument(
        "--html-file",
        type=Path,
        help="Use local HTML file instead of fetching URL (useful for bot-protected pages).",
    )
    parser.add_argument(
        "--selector",
        help="Optional CSS selector to force transcript container extraction.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Output directory for JSON file (default: current directory).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional explicit output path. Overrides --output-dir and auto filename.",
    )
    parser.add_argument("--podcast-name", help="Override inferred podcast name.")
    parser.add_argument("--episode-title", help="Override inferred episode title.")
    parser.add_argument(
        "--episode-date",
        help="Override inferred episode date (YYYY-MM-DD preferred).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--version",
        default="v1",
        help="Filename version suffix (default: v1).",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=40,
        help="Minimum transcript word count required before failing (default: 40).",
    )
    parser.add_argument(
        "--cloudscraper-fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Automatically retry fetch with cloudscraper when direct requests fetch is blocked "
            "(default: enabled)."
        ),
    )
    return parser.parse_args()


def slugify(value: str, fallback: str = "unknown") -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or fallback


def normalize_line(line: str) -> str:
    return WHITESPACE_RE.sub(" ", line).strip()


def should_drop_line(line: str) -> bool:
    lowered = line.lower().strip(" .")
    if not lowered:
        return True
    if lowered in NOISE_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in NOISE_PREFIXES)


def is_challenge_page(html: str) -> bool:
    lower = html.lower()
    markers = (
        "enable javascript and cookies to continue",
        "cf-challenge",
        "just a moment...",
        "_cf_chl_opt",
        "attention required!",
        "please stand by, while we are checking your browser",
    )
    return any(marker in lower for marker in markers)


def fetch_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def is_probably_bot_block(exc: requests.RequestException) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is not None and response.status_code in {403, 429, 503}:
            return True
    return False


def fetch_html_with_cloudscraper(url: str, timeout: int) -> str:
    try:
        import cloudscraper  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TranscriptExtractionError(
            "Direct fetch appears blocked and cloudscraper is unavailable. "
            "Install it with `uv add cloudscraper` or rerun with "
            "`uv run --with cloudscraper ...`."
        ) from exc

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "desktop": True}
    )
    try:
        response = scraper.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TranscriptExtractionError(f"cloudscraper fallback failed: {exc}") from exc

    return response.text


def parse_json_ld(soup: BeautifulSoup) -> list[dict]:
    parsed: list[dict] = []
    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script_tag.string or script_tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        parsed.extend(flatten_json_ld(data))
    return parsed


def flatten_json_ld(payload: object) -> list[dict]:
    items: list[dict] = []
    if isinstance(payload, dict):
        items.append(payload)
        graph = payload.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                items.extend(flatten_json_ld(item))
    elif isinstance(payload, list):
        for item in payload:
            items.extend(flatten_json_ld(item))
    return [item for item in items if isinstance(item, dict)]


def first_non_empty(values: list[str | None]) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None

    value = raw.strip()
    if not value:
        return None

    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
    if iso_match:
        return iso_match.group(0)

    slash_match = re.search(r"\b\d{4}/\d{2}/\d{2}\b", value)
    if slash_match:
        return slash_match.group(0).replace("/", "-")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        pass

    for fmt in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y.%m.%d",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def domain_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    root = host.split(".")[0] if host else "web"
    return root.replace("-", " ").strip() or "web"


def meta_content(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    # BeautifulSoup find signature: find(name, attrs, recursive, string, **kwargs).
    # Build attrs with literals so type checkers can resolve the overload cleanly.
    if property_name and name:
        tag = soup.find("meta", attrs={"property": property_name, "name": name})
    elif property_name:
        tag = soup.find("meta", attrs={"property": property_name})
    elif name:
        tag = soup.find("meta", attrs={"name": name})
    else:
        return None

    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def safe_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def pick_json_ld_value(items: list[dict], keys: tuple[str, ...]) -> str | None:
    for item in items:
        for key in keys:
            value = safe_str(item.get(key))
            if value:
                return value
    return None


def pick_json_ld_part_of_name(items: list[dict]) -> str | None:
    for item in items:
        part_of = item.get("isPartOf")
        if isinstance(part_of, dict):
            name = safe_str(part_of.get("name"))
            if name:
                return name
        if isinstance(part_of, list):
            for candidate in part_of:
                if isinstance(candidate, dict):
                    name = safe_str(candidate.get("name"))
                    if name:
                        return name
    return None


def split_title(value: str, podcast_name: str | None) -> str:
    separators = (" | ", " - ", " — ", " :: ")
    for sep in separators:
        if sep not in value:
            continue
        parts = [part.strip() for part in value.split(sep) if part.strip()]
        if len(parts) < 2:
            continue
        if podcast_name:
            podcast_slug = slugify(podcast_name)
            for part in parts[1:]:
                if slugify(part) == podcast_slug:
                    return parts[0]
        if len(parts[0]) >= 8:
            return parts[0]
    return value.strip()


def infer_metadata(
    soup: BeautifulSoup,
    *,
    url: str,
    podcast_name_override: str | None,
    episode_title_override: str | None,
    episode_date_override: str | None,
) -> tuple[str, str, str | None]:
    json_ld_items = parse_json_ld(soup)

    inferred_podcast = first_non_empty(
        [
            podcast_name_override,
            pick_json_ld_part_of_name(json_ld_items),
            meta_content(soup, property_name="og:site_name"),
            domain_name_from_url(url),
        ]
    )
    podcast_name = inferred_podcast or "web"

    title_candidates = [
        episode_title_override,
        pick_json_ld_value(json_ld_items, TITLE_CANDIDATE_KEYS),
        meta_content(soup, property_name="og:title"),
        meta_content(soup, name="twitter:title"),
    ]

    h1_tag = soup.find("h1")
    if h1_tag:
        title_candidates.append(h1_tag.get_text(" ", strip=True))

    if soup.title and soup.title.string:
        title_candidates.append(soup.title.string.strip())

    raw_title = first_non_empty(title_candidates) or "episode"
    episode_title = split_title(raw_title, podcast_name)

    date_candidates = [
        episode_date_override,
        pick_json_ld_value(json_ld_items, DATE_CANDIDATE_KEYS),
        meta_content(soup, property_name="article:published_time"),
        meta_content(soup, property_name="og:published_time"),
        meta_content(soup, name="pubdate"),
        meta_content(soup, name="date"),
    ]

    published_date = None
    for candidate in date_candidates:
        normalized = normalize_date(candidate)
        if normalized:
            published_date = normalized
            break

    return podcast_name, episode_title, published_date


def cleaned_text_from_node(node: Tag) -> str:
    cloned = BeautifulSoup(str(node), "html.parser")
    for selector in REMOVAL_SELECTORS:
        for removable in cloned.select(selector):
            removable.decompose()

    lines: list[str] = []
    for raw_line in cloned.get_text("\n").splitlines():
        line = normalize_line(raw_line)
        if should_drop_line(line):
            continue
        lines.append(line)

    deduped: list[str] = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)

    return "\n\n".join(deduped)


def score_candidate(text: str, selector_hint: str) -> int:
    words = len(text.split())
    score = words
    if "transcript" in selector_hint:
        score += 260
    if TIMESTAMP_RE.search(text):
        score += 300
    if "transcript" in text.lower()[:1200]:
        score += 100
    if selector_hint in {"article", "main", ".entry-content", ".post-content"}:
        score += 30
    if words < 40:
        score -= 250
    return score


def extract_transcript_text(soup: BeautifulSoup, selector: str | None) -> str:
    if selector:
        selected = soup.select(selector)
        if not selected:
            raise TranscriptExtractionError(f"Selector '{selector}' did not match any elements.")
        transcript = cleaned_text_from_node(selected[0])
        if transcript:
            return transcript
        raise TranscriptExtractionError(f"Selector '{selector}' matched an empty transcript block.")

    best_text = ""
    best_score = -10**9

    seen_nodes: set[int] = set()
    for candidate_selector in CANDIDATE_SELECTORS:
        for node in soup.select(candidate_selector):
            node_id = id(node)
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)

            if not isinstance(node, Tag):
                continue

            text = cleaned_text_from_node(node)
            if not text:
                continue

            score = score_candidate(text, candidate_selector)
            if score > best_score:
                best_score = score
                best_text = text

    if not best_text:
        raise TranscriptExtractionError("Unable to extract transcript content from page.")

    return best_text


def find_timestamp_line_indexes(lines: list[str]) -> list[int]:
    return [idx for idx, line in enumerate(lines) if TIMESTAMP_RE.search(line)]


def find_transcript_start(lines: list[str], timestamp_indexes: list[int]) -> int | None:
    if len(timestamp_indexes) < 3:
        return None

    for idx in timestamp_indexes:
        if SPEAKER_TIMESTAMP_LINE_RE.search(lines[idx]):
            return idx

    for idx in timestamp_indexes:
        if TIMESTAMP_ONLY_LINE_RE.search(lines[idx]):
            return idx

    return timestamp_indexes[0]


def find_transcript_end(lines: list[str], timestamp_indexes: list[int]) -> int | None:
    if not timestamp_indexes:
        return None

    last_timestamp_idx = timestamp_indexes[-1]
    for idx in range(last_timestamp_idx + 1, len(lines)):
        lowered = lines[idx].lower()
        if lowered in TAIL_CUTOFF_EXACT_LINES:
            return idx
        if any(marker in lowered for marker in TAIL_CUTOFF_MARKERS):
            return idx

    return None


def trim_transcript_noise(text: str) -> str:
    lines = [normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return text

    timestamp_indexes = find_timestamp_line_indexes(lines)

    start_idx = find_transcript_start(lines, timestamp_indexes)
    if start_idx is not None and start_idx > 0:
        lines = lines[start_idx:]
        timestamp_indexes = [idx - start_idx for idx in timestamp_indexes if idx >= start_idx]

    end_idx = find_transcript_end(lines, timestamp_indexes)
    if end_idx is not None:
        lines = lines[:end_idx]

    return "\n\n".join(lines)


def build_output_path(
    *,
    output_dir: Path,
    output_file: Path | None,
    podcast_name: str,
    episode_title: str,
    episode_date: str,
    version: str,
) -> Path:
    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        return output_file

    podcast_slug = slugify(podcast_name, fallback="web")
    episode_slug = slugify(episode_title, fallback="episode")
    date_slug = normalize_date(episode_date) or date.today().isoformat()
    version_slug = slugify(version, fallback="v1")

    filename = f"web__{podcast_slug}__{episode_slug}__{date_slug}__{version_slug}.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / filename


def main() -> int:
    args = parse_args()

    try:
        if args.html_file:
            html = args.html_file.read_text(encoding="utf-8")
        else:
            try:
                html = fetch_html(args.url, args.timeout)
            except requests.RequestException as exc:
                if args.cloudscraper_fallback and is_probably_bot_block(exc):
                    html = fetch_html_with_cloudscraper(args.url, args.timeout)
                else:
                    raise
    except FileNotFoundError as exc:
        print(f"Error: HTML file not found: {exc.filename}", file=sys.stderr)
        return 1
    except TranscriptExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(
            "Error: failed to fetch URL: "
            f"{exc}. Try --html-file for saved page content or install cloudscraper "
            "for blocked pages.",
            file=sys.stderr,
        )
        return 1

    if is_challenge_page(html) and not args.html_file:
        if args.cloudscraper_fallback:
            try:
                html = fetch_html_with_cloudscraper(args.url, args.timeout)
            except TranscriptExtractionError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            if is_challenge_page(html):
                print(
                    "Error: page appears bot-protected even after cloudscraper fallback. "
                    "Save page HTML via browser and rerun with --html-file.",
                    file=sys.stderr,
                )
                return 1
        else:
            print(
                "Error: page appears bot-protected (challenge page returned). "
                "Enable --cloudscraper-fallback or save page HTML via browser and rerun with --html-file.",
                file=sys.stderr,
            )
            return 1

    soup = BeautifulSoup(html, "html.parser")

    try:
        podcast_name, episode_title, published_date = infer_metadata(
            soup,
            url=args.url,
            podcast_name_override=args.podcast_name,
            episode_title_override=args.episode_title,
            episode_date_override=args.episode_date,
        )

        transcript_text = extract_transcript_text(soup, args.selector)
        transcript_text = trim_transcript_noise(transcript_text)
    except TranscriptExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    word_count = len(transcript_text.split())
    if word_count < args.min_words:
        print(
            f"Error: extracted text is too short ({word_count} words). "
            "Provide --selector or --html-file with cleaned page source.",
            file=sys.stderr,
        )
        return 1

    retrieved_at = date.today().isoformat()
    canonical_date = published_date or normalize_date(args.episode_date) or retrieved_at

    output_path = build_output_path(
        output_dir=args.output_dir,
        output_file=args.output_file,
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date=canonical_date,
        version=args.version,
    )

    document = {
        "doc_id": output_path.stem,
        "source": {
            "type": "web_transcript",
            "url": args.url,
            "retrieved_at": retrieved_at,
        },
        "episode": {
            "podcast_name": podcast_name,
            "title": episode_title,
            "published_date": canonical_date,
        },
        "raw": transcript_text,
    }

    output_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {output_path}")
    print(
        "Metadata: "
        f"podcast_name='{podcast_name}', title='{episode_title}', published_date='{canonical_date}', words={word_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
