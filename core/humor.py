"""Small, local controls for Bombaclat's conversational humor.

Humor here is treated as a conversational choice, not a personality setting.
The useful signal is a short, specific reply that fits the preceding turn. The
calibration examples are deliberately few and are presented as mechanisms to
copy, never as lines to repeat.
"""

from __future__ import annotations

import json
from typing import Any


# These are examples observed in Bombaclat's own recent chat history. They are
# intentionally short: the model needs to learn the rhythm, not perform a
# five-line comedy routine.
DEFAULT_GOOD_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("i'm not that stupid gang", "sure you aren't"),
    ("asd", "keyboard gave up before you did huh"),
    (
        "post a ishowspeed meme",
        "figures you want the vehicular manslaughter tier of speed clips",
    ),
    (
        "or it's just an image",
        "fair enough, temu shipping on a whole car would take months anyway",
    ),
)


def _short(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _context_example(row: dict[str, Any]) -> tuple[str, str] | None:
    response = _short(row.get("response_text"), 240)
    if not response:
        return None
    try:
        context = json.loads(row.get("context_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        context = []
    if not isinstance(context, list):
        context = []
    human_lines = [
        _short(item.get("content"), 220)
        for item in context
        if isinstance(item, dict) and not item.get("is_bot") and item.get("content")
    ]
    return (human_lines[-1] if human_lines else "a message in chat", response)


def build_calibration(
    good_rows: list[dict[str, Any]] | None = None,
    bad_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Build a compact prompt block from defaults and explicit owner feedback."""
    examples: list[tuple[str, str]] = list(DEFAULT_GOOD_EXAMPLES)
    for row in good_rows or []:
        example = _context_example(row)
        if example and example not in examples:
            examples.append(example)
        if len(examples) >= 7:
            break

    lines = [
        "<humor_calibration>",
        "humor is optional. this is a chat with friends, not an open-mic set.",
        "the successful rhythm here is compressed, specific, and slightly deadpan:",
    ]
    for setup, reply in examples[:7]:
        lines.append(f'- setup: "{setup}" -> reply: "{reply}"')
    lines.extend(
        (
            "copy the mechanism, not the wording: short reversal, concrete detail, or one-step escalation.",
            "slang is seasoning, not a costume. only use bro, gng, lowk, etc. when the current chat naturally supports it.",
            "if the setup is weak, answer normally or use one reaction. do not manufacture a comparison, a fake threat, or a dramatic verdict.",
        )
    )
    bad_notes = [
        _short(row.get("note"), 180)
        for row in bad_rows or []
        if _short(row.get("note"), 180)
    ]
    if bad_notes:
        lines.append("owner corrections to remember:")
        lines.extend(f"- {note}" for note in bad_notes[:4])
    lines.append("</humor_calibration>")
    return "\n".join(lines)


def feedback_usage() -> str:
    return (
        "reply to one of my messages with `!humor good` when it actually lands, "
        "or `!humor bad <what was wrong>` when it misses"
    )
