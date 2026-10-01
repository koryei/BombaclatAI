"""Read the current changelog feed and the complete historical archive."""

import hashlib
import json
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LATEST_CHANGES_PATH = _PROJECT_ROOT / "LATEST_CHANGES.md"
_CHANGELOG_PATH = _PROJECT_ROOT / "CHANGELOG.md"


def _parse_entries(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    entries = []
    for section in sections[: max(0, limit)]:
        lines = section.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()

        # Fold wrapped markdown bullets back into the previous bullet.
        bullets: list[str] = []
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("-"):
                bullets.append(stripped.lstrip("-").strip())
            elif bullets:
                bullets[-1] = f"{bullets[-1]} {stripped}"

        entries.append({"title": title, "bullets": bullets})
    return entries


def get_latest_entries(limit: int = 5) -> list[dict]:
    """Read the curated current update feed, falling back to the archive."""
    entries = _parse_entries(_LATEST_CHANGES_PATH, limit)
    return entries or _parse_entries(_CHANGELOG_PATH, limit)


def get_recent_entries(limit: int = 3) -> list[dict]:
    """Read the latest sections from the complete historical CHANGELOG archive."""
    return _parse_entries(_CHANGELOG_PATH, limit)


def entry_fingerprint(entry: dict) -> str:
    """Return a stable identity for an update's title and bullet content."""
    normalized = json.dumps(
        {
            "title": str(entry.get("title", "")),
            "bullets": [str(bullet) for bullet in entry.get("bullets", [])],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_tracking_state(entries: list[dict]) -> dict[str, object]:
    """Build the persisted state used to detect new or edited update entries."""
    return {
        "version": 2,
        "entries": {
            str(entry.get("title", "")): entry_fingerprint(entry)
            for entry in entries
            if entry.get("title")
        },
    }


def parse_tracking_state(raw: str | None) -> tuple[dict[str, str], bool]:
    """Read current fingerprint state and identify the old title-only format.

    Older versions persisted a JSON list of titles.  The boolean lets the
    caller perform a one-time migration without silently losing an update that
    changed while that weaker format was active.
    """
    try:
        parsed = json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return {}, False

    if isinstance(parsed, dict) and isinstance(parsed.get("entries"), dict):
        return {
            str(title): str(fingerprint)
            for title, fingerprint in parsed["entries"].items()
            if title and fingerprint
        }, False

    if isinstance(parsed, list):
        return {str(title): "" for title in parsed if isinstance(title, str) and title}, True

    return {}, False
