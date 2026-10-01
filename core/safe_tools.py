"""Bounded, read-only helpers exposed through the model tool layer.

Nothing in this module executes user code or grants the model arbitrary network
access. Public HTTP is restricted to HTTPS hosts that resolve to public IPs,
and arithmetic is evaluated through a small AST allowlist.
"""

import ast
import asyncio
import ipaddress
import math
import re
import socket
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

from core.serper_client import (
    SerperError,
    search_public_web as _serper_search,
)


class SafeToolError(ValueError):
    """A user-facing, bounded safe-tool failure."""


_MAX_PAGE_BYTES = 512 * 1024
_MAX_PAGE_TEXT_CHARS = 9000
_PUBLIC_READ_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36 BombaclatAI/1.0"
)


class _VisibleTextParser(HTMLParser):
    _SKIP_TAGS: ClassVar[set[str]] = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title" and self._skip_depth == 0:
            self._in_title = True
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.parts.append(cleaned)
        if self._in_title:
            self.title_parts.append(cleaned)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()[:300]

    @property
    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts)).strip()



class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_public_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    if len(url) > 2048:
        raise SafeToolError("url is too long")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise SafeToolError("only public https URLs are allowed")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise SafeToolError("that URL contains a blocked credential or port")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise SafeToolError("private hostnames are blocked")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError) as exc:
            raise SafeToolError("the public host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise SafeToolError("private or reserved network addresses are blocked")
    return urlunsplit(("https", hostname, parsed.path or "/", parsed.query, ""))


def _read_public_url(url: str, *, max_bytes: int = _MAX_PAGE_BYTES) -> tuple[str, bytes, str]:
    validated = _validate_public_url(url)
    request = urllib.request.Request(
        validated,
        headers={
            "User-Agent": _PUBLIC_READ_USER_AGENT,
            "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.1",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=8) as response:
            content_type = response.headers.get_content_type().lower()
            data = response.read(max_bytes + 1)
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        raise SafeToolError(f"public page returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SafeToolError("public page could not be reached") from exc
    if len(data) > max_bytes:
        raise SafeToolError("public page is too large")
    _validate_public_url(final_url)
    return content_type, data, final_url


async def search_public_web(
    query: str,
    max_results: int = 5,
    *,
    freshness: str = "noLimit",
    summary: bool = True,
) -> str:
    try:
        return await _serper_search(
            query,
            max_results,
            freshness=freshness,
            summary=summary,
        )
    except SerperError:
        return "public search unavailable"


async def fetch_public_page(url: str) -> str:
    content_type, data, final_url = await asyncio.to_thread(_read_public_url, url)
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleTextParser()
        parser.feed(data.decode("utf-8", errors="replace"))
        text = parser.text
        title = parser.title
    elif content_type in {"text/plain", "application/json"}:
        title = ""
        text = data.decode("utf-8", errors="replace")
    else:
        raise SafeToolError("only public text or HTML pages can be summarized")
    if not text:
        raise SafeToolError("public page did not contain readable text")
    header = f"public page: {title}\nurl: {final_url}" if title else f"public page\nurl: {final_url}"
    return f"{header}\n{text[:_MAX_PAGE_TEXT_CHARS]}"


_UNIT_TABLE = {
    "mm": ("length", 0.001),
    "millimeter": ("length", 0.001),
    "millimeters": ("length", 0.001),
    "cm": ("length", 0.01),
    "centimeter": ("length", 0.01),
    "centimeters": ("length", 0.01),
    "m": ("length", 1.0),
    "meter": ("length", 1.0),
    "meters": ("length", 1.0),
    "km": ("length", 1000.0),
    "kilometer": ("length", 1000.0),
    "kilometers": ("length", 1000.0),
    "in": ("length", 0.0254),
    "inch": ("length", 0.0254),
    "inches": ("length", 0.0254),
    "ft": ("length", 0.3048),
    "foot": ("length", 0.3048),
    "feet": ("length", 0.3048),
    "yd": ("length", 0.9144),
    "yard": ("length", 0.9144),
    "yards": ("length", 0.9144),
    "mi": ("length", 1609.344),
    "mile": ("length", 1609.344),
    "miles": ("length", 1609.344),
    "g": ("mass", 1.0),
    "gram": ("mass", 1.0),
    "grams": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "kilogram": ("mass", 1000.0),
    "kilograms": ("mass", 1000.0),
    "oz": ("mass", 28.349523125),
    "ounce": ("mass", 28.349523125),
    "ounces": ("mass", 28.349523125),
    "lb": ("mass", 453.59237),
    "lbs": ("mass", 453.59237),
    "pound": ("mass", 453.59237),
    "pounds": ("mass", 453.59237),
    "s": ("time", 1.0),
    "sec": ("time", 1.0),
    "second": ("time", 1.0),
    "seconds": ("time", 1.0),
    "min": ("time", 60.0),
    "minute": ("time", 60.0),
    "minutes": ("time", 60.0),
    "h": ("time", 3600.0),
    "hr": ("time", 3600.0),
    "hour": ("time", 3600.0),
    "hours": ("time", 3600.0),
    "day": ("time", 86400.0),
    "days": ("time", 86400.0),
    "week": ("time", 604800.0),
    "weeks": ("time", 604800.0),
    "b": ("data", 1.0),
    "kb": ("data", 1000.0),
    "mb": ("data", 1000.0**2),
    "gb": ("data", 1000.0**3),
    "tb": ("data", 1000.0**4),
    "bytes": ("data", 1.0),
    "byte": ("data", 1.0),
}


def _format_number(value: float) -> str:
    if not math.isfinite(value) or abs(value) > 1e100:
        raise SafeToolError("calculation result is outside the safe range")
    if abs(value - round(value)) < 1e-10:
        return str(round(value))
    return f"{value:.12g}"


def _evaluate_ast(node) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_ast(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
        left = _evaluate_ast(node.left)
        right = _evaluate_ast(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise SafeToolError("cannot divide by zero")
            return left / right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise SafeToolError("cannot use zero as a remainder divisor")
            return left % right
        if abs(right) > 100 or abs(left) > 1e12:
            raise SafeToolError("exponent is outside the safe range")
        return left**right
    raise SafeToolError("only basic arithmetic is supported")


def calculate_expression(expression: str) -> str:
    raw = " ".join(str(expression or "").split()).strip()
    if not raw or len(raw) > 240:
        raise SafeToolError("calculation must be short and non-empty")

    percentage = re.fullmatch(r"([+-]?[\d,.]+)\s*%\s*(?:of)\s*([+-]?[\d,.]+)", raw, re.IGNORECASE)
    if percentage:
        percent = float(percentage.group(1).replace(",", ""))
        total = float(percentage.group(2).replace(",", ""))
        return f"{percent}% of {total:g} = {_format_number(total * percent / 100)}"

    date_difference = re.fullmatch(
        r"days?\s+between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})",
        raw,
        re.IGNORECASE,
    )
    if date_difference:
        first = date.fromisoformat(date_difference.group(1))
        second = date.fromisoformat(date_difference.group(2))
        return f"{abs((second - first).days)} days"

    conversion = re.fullmatch(
        r"(?:convert\s+)?([+-]?[\d,.]+)\s*([a-zA-Z]+)\s+(?:to|in)\s+([a-zA-Z]+)",
        raw,
        re.IGNORECASE,
    )
    if conversion:
        value = float(conversion.group(1).replace(",", ""))
        from_unit = conversion.group(2).lower()
        to_unit = conversion.group(3).lower()
        if from_unit in {"c", "celsius", "f", "fahrenheit", "k", "kelvin"} and to_unit in {
            "c", "celsius", "f", "fahrenheit", "k", "kelvin"
        }:
            if from_unit in {"f", "fahrenheit"}:
                celsius = (value - 32) * 5 / 9
            elif from_unit in {"k", "kelvin"}:
                celsius = value - 273.15
            else:
                celsius = value
            if to_unit in {"f", "fahrenheit"}:
                converted = celsius * 9 / 5 + 32
            elif to_unit in {"k", "kelvin"}:
                converted = celsius + 273.15
            else:
                converted = celsius
            return f"{_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"
        if from_unit not in _UNIT_TABLE or to_unit not in _UNIT_TABLE:
            raise SafeToolError("that unit is not supported")
        from_category, from_factor = _UNIT_TABLE[from_unit]
        to_category, to_factor = _UNIT_TABLE[to_unit]
        if from_category != to_category:
            raise SafeToolError("those units are not compatible")
        converted = value * from_factor / to_factor
        return f"{_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"

    expression_text = raw.replace("^", "**")
    expression_text = expression_text.replace(",", "")
    if expression_text.startswith("$"):
        expression_text = expression_text[1:].strip()
    if len(expression_text) > 240 or re.search(r"[^0-9eE+*/%().\-\s]", expression_text):
        raise SafeToolError("only basic arithmetic, percentages, dates, and unit conversions are supported")
    try:
        tree = ast.parse(expression_text, mode="eval")
        result = _evaluate_ast(tree)
    except (SyntaxError, ValueError, OverflowError) as exc:
        raise SafeToolError("that calculation could not be parsed") from exc
    return f"{expression} = {_format_number(result)}"
