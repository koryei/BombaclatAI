"""Helpers for Bombaclat's one-time GIF classification library.

GIFs are learned from a user-controlled Discord channel, classified once by
the configured vision model, and then reused by label without repeated image
requests. Only HTTPS media from known Discord/GIF hosts is fetched.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


GIF_CATEGORIES: tuple[str, ...] = (
    "confusion",
    "disbelief",
    "roast",
    "sad",
    "celebration",
    "approval",
    "shock",
    "awkward",
    "laugh",
    "support",
    "anger",
    "other",
)

_GIF_URL_RE = re.compile(r"https://[^\s<>\]\[()]+", re.IGNORECASE)
_GIF_EXTENSIONS = (".gif", ".webp", ".png", ".jpg", ".jpeg")
_ALLOWED_HOSTS = (
    "tenor.com",
    "giphy.com",
    "discordapp.com",
    "discordapp.net",
)
_MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
_USER_AGENT = "BombaclatAI-GIF-Library/1.0"


@dataclass(frozen=True)
class GifSource:
    url: str
    mime_type: str | None = None
    attachment: Any = None


def _allowed_host(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    return parsed.scheme == "https" and any(
        hostname == host or hostname.endswith(f".{host}") for host in _ALLOWED_HOSTS
    )


def source_key(url: str) -> str:
    """Return a stable identity for media whose CDN query string rotates."""
    parsed = urlsplit(str(url or ""))
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    path = parsed.path or "/"
    if hostname.endswith("discordapp.com") or hostname.endswith("discordapp.net"):
        return f"discord:{path}"
    return f"{hostname}:{path}"


def _looks_like_media_url(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return path.endswith(_GIF_EXTENSIONS) or any(
        marker in urlsplit(url).hostname.casefold()
        for marker in ("media.tenor.com", "media.giphy.com", "cdn.discordapp.com", "media.discordapp.net")
        if urlsplit(url).hostname
    )


def _clean_url(raw_url: Any) -> str:
    url = str(raw_url or "").strip().rstrip(".,!?;:")
    return url if _allowed_host(url) else ""


def extract_gif_sources(message: Any) -> list[GifSource]:
    """Collect direct media URLs from attachments, embeds, and message text."""
    sources: list[GifSource] = []
    # Discord can expose one upload through several URLs at once: the
    # attachment URL, an embed image, a thumbnail, and a signed CDN variant.
    # Those URLs are different strings but the same underlying media. Keep
    # the first usable representation and dedupe by stable source identity.
    seen: set[str] = set()

    def add(raw_url: Any, mime_type: str | None = None, attachment: Any = None) -> None:
        url = _clean_url(raw_url)
        key = source_key(url) if url else ""
        if not url or key in seen:
            return
        if attachment is None and not _looks_like_media_url(url):
            return
        seen.add(key)
        sources.append(GifSource(url=url, mime_type=mime_type, attachment=attachment))

    for attachment in list(getattr(message, "attachments", ()) or ()):
        filename = str(getattr(attachment, "filename", "") or "").casefold()
        content_type = str(getattr(attachment, "content_type", "") or "").split(";", 1)[0].casefold()
        if content_type.startswith("image/") or filename.endswith(_GIF_EXTENSIONS):
            add(getattr(attachment, "url", ""), content_type or None, attachment)

    for embed in list(getattr(message, "embeds", ()) or ()):
        image = getattr(embed, "image", None)
        thumbnail = getattr(embed, "thumbnail", None)
        add(getattr(image, "url", ""))
        add(getattr(thumbnail, "url", ""))

    for raw_url in _GIF_URL_RE.findall(str(getattr(message, "content", "") or "")):
        add(raw_url)

    return sources


async def read_source(source: GifSource, *, max_bytes: int = _MAX_DOWNLOAD_BYTES) -> tuple[str, bytes] | None:
    """Read an attachment or known-host media URL into bounded memory.

    Keep this small wrapper for callers that only need the media. The detailed
    variant is used by the learning command so it can explain why a source was
    skipped.
    """
    media, _reason = await read_source_detailed(source, max_bytes=max_bytes)
    return media


async def read_source_detailed(
    source: GifSource,
    *,
    max_bytes: int = _MAX_DOWNLOAD_BYTES,
) -> tuple[tuple[str, bytes] | None, str]:
    """Read media and return a safe, coarse failure reason when it is skipped.

    Discord attachments are normally readable through ``Attachment.read``.
    Some self-bot Discord forks, expired attachment objects, and older cached
    messages make that call fail even though the signed CDN URL still works,
    so attachments deliberately fall through to the URL fetch below.
    """
    attachment_reason = ""
    if source.attachment is not None:
        reader = getattr(source.attachment, "read", None)
        if callable(reader):
            try:
                data = reader(use_cached=False)
                if inspect.isawaitable(data):
                    data = await data
                if isinstance(data, bytes) and 0 < len(data) <= max_bytes:
                    mime = source.mime_type or "image/gif"
                    return (mime if mime.startswith("image/") else "image/gif", data), "ok"
                attachment_reason = "too_large" if isinstance(data, bytes) else "empty"
            except Exception:
                attachment_reason = "attachment_read"

    if not _allowed_host(source.url):
        return None, "unsupported_url"

    def fetch() -> tuple[tuple[str, bytes] | None, str]:
        request = urllib.request.Request(source.url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                content_type = str(response.headers.get_content_type() or "").casefold()
                if not content_type.startswith("image/"):
                    return None, "unsupported_type"
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    return None, "too_large"
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    return None, "too_large"
                if not data:
                    return None, "empty"
                return (content_type, data), "ok"
        except urllib.error.HTTPError as exc:
            return None, f"http_{exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return None, "network"

    media, reason = await asyncio.to_thread(fetch)
    if media is not None:
        return media, "ok"
    return None, reason if reason != "network" or not attachment_reason else attachment_reason


def parse_classification(raw: str | None) -> dict[str, Any] | None:
    """Parse the model's JSON while tolerating a markdown code fence."""
    text = str(raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None

    raw_categories = parsed.get("categories", parsed.get("category", []))
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    if not isinstance(raw_categories, list):
        raw_categories = []
    categories = []
    for item in raw_categories:
        category = str(item).strip().casefold()
        if category in GIF_CATEGORIES and category not in categories:
            categories.append(category)
    if not categories:
        categories = ["other"]
    try:
        confidence = max(0.0, min(float(parsed.get("confidence", 0.5)), 1.0))
    except (TypeError, ValueError):
        confidence = 0.5
    description = " ".join(str(parsed.get("description", "usable reaction GIF")).split())[:240]
    return {"categories": categories[:3], "confidence": confidence, "description": description}
