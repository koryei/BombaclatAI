"""Freshness intent classification for direct user requests.

The model still owns normal tool selection. This module only provides a small,
conservative policy signal and the application backstop for unmistakable current
information requests.
"""

import dataclasses
import re
import typing


FreshnessMode = typing.Literal["search_now", "ask_first", "answer_without_search"]

_CURRENT_MARKERS = (
    "latest",
    "recent",
    "current",
    "newest",
    "today",
    "tomorrow",
    "tonight",
    "right now",
    "this week",
    "this month",
    "this year",
    "news",
    "updates",
    "patch notes",
    "release date",
    "releasing",
    "coming out",
    "as of",
    "upcoming",
    "coming month",
    "next month",
    "next few weeks",
    "in the next",
    "soon",
)
_EXPLICIT_SEARCH_RE = re.compile(
    r"\b(?:search|lookup|look\s+up|check\s+online|look\s+online|find\s+online|google)\b",
    re.IGNORECASE,
)
_AMBIGUOUS_PATTERNS = (
    "what's going on with",
    "whats going on with",
    "what is going on with",
    "what happened with",
    "what happened to",
    "any word on",
    "heard anything about",
    "what's new with",
    "whats new with",
)
_HISTORICAL_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_MENTION_RE = re.compile(r"<@!?\d+>")


@dataclasses.dataclass(frozen=True)
class FreshnessRequest:
    mode: FreshnessMode
    query: str
    freshness: str = "noLimit"
    reason: str = ""

    @property
    def must_search(self) -> bool:
        return self.mode == "search_now"


def _normalize(content: str) -> str:
    without_mentions = _MENTION_RE.sub(" ", content or "")
    return " ".join(without_mentions.casefold().split()).strip()


def _contains_marker(text: str, marker: str) -> bool:
    if " " in marker:
        return marker in text
    return bool(re.search(rf"\b{re.escape(marker)}\b", text))


def _freshness_window(text: str) -> str:
    if any(_contains_marker(text, marker) for marker in ("today", "tomorrow", "tonight", "right now")):
        return "oneDay"
    if _contains_marker(text, "this week"):
        return "oneWeek"
    if _contains_marker(text, "this year"):
        return "oneYear"
    if any(
        _contains_marker(text, marker)
        for marker in (
            "latest",
            "recent",
            "current",
            "newest",
            "this month",
            "upcoming",
            "coming month",
            "next month",
            "next few weeks",
            "in the next",
            "soon",
            "news",
            "updates",
            "patch notes",
            "releasing",
        )
    ):
        return "oneMonth"
    return "noLimit"


def _is_local_request(text: str, local_markers: tuple[str, ...]) -> bool:
    return any(marker.casefold() in text for marker in local_markers)


def classify_freshness(
    content: str,
    *,
    local_markers: tuple[str, ...] = (),
) -> FreshnessRequest:
    """Classify a direct message without making a network request."""
    normalized = _normalize(content)
    if not normalized or _is_local_request(normalized, local_markers):
        return FreshnessRequest("answer_without_search", normalized, reason="empty or local request")

    if _HISTORICAL_RE.search(normalized) and not any(
        _contains_marker(normalized, marker)
        for marker in ("today", "current", "latest", "recent", "news", "upcoming", "releasing", "release date")
    ):
        return FreshnessRequest("answer_without_search", normalized, reason="historical-looking request")

    if _EXPLICIT_SEARCH_RE.search(normalized):
        return FreshnessRequest(
            "search_now",
            normalized[:240],
            freshness=_freshness_window(normalized),
            reason="user explicitly requested a search",
        )

    if any(_contains_marker(normalized, marker) for marker in _CURRENT_MARKERS):
        return FreshnessRequest(
            "search_now",
            normalized[:240],
            freshness=_freshness_window(normalized),
            reason="clear current-information request",
        )

    if any(pattern in normalized for pattern in _AMBIGUOUS_PATTERNS):
        return FreshnessRequest(
            "ask_first",
            normalized[:240],
            freshness="oneMonth",
            reason="current intent is possible but not explicit",
        )

    return FreshnessRequest("answer_without_search", normalized, reason="no freshness signal")
