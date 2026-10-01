"""Lightweight, dependency-free pattern detectors.

Each detector looks at the recent message window and returns a raw score
from 0.0 (no signal) to 1.0 (strong signal). These raw scores get multiplied
by learned weights in the decision engine, so a detector doesn't need to be
perfect - it just needs to be a consistent, cheap signal that the learning
loop can tune over time based on real feedback.
"""

import re
import time
from typing import Callable

from core.models import MessageRecord

_SADNESS_WORDS = (
    "i feel like shit", "i'm so sad", "im so sad", "i hate my life", "i hate myself",
    "depressed", "depressing", "sucks so bad", "so tired of this", "tired of everything",
    "wanna cry", "want to cry", "crying rn", "feel like garbage", "feel so alone",
    "nobody cares", "no one cares", "i give up", "i'm done", "im done",
    "this sucks", "worst day", "everything is going wrong", "i'm not okay", "im not okay",
)

_CELEBRATION_WORDS = (
    "lets goo", "let's goo", "lessgoo", "finally!", "yessss", "yesss", "we did it",
    "i did it", "i won", "i got it", "i passed", "i got in", "hell yeah", "hell yea",
    "big w", "huge w", "dub", "goated", "lfg", "pog", "poggers", "we won", "i made it",
)

_HELP_WORDS = (
    "how do i", "how do you", "how to", "do you know how", "dyk how", "anyone know how",
    "can someone help", "can anyone help", "can u help", "can you help", "help me",
    "i need help", "please help", "help with", "i'm stuck", "im stuck",
    "stuck on", "idk how to", "i dont know how", "i don't know how", "does anyone know",
    "need help with", "someone explain", "can somebody help", "what am i doing wrong",
    "what are", "what is", "what's", "whats", "tell me", "recent updates", "latest updates",
    "recent news", "latest news", "patch notes",
    "this isn't working", "this isnt working", "why isn't this working",
)

_ESCALATION_WORDS = (
    "fuck you", "shut the fuck up", "shut up", "stfu", "fuck off", "i'm done with you",
    "im done with you", "you're an idiot", "youre an idiot", "you're annoying", "youre annoying",
    "stop talking to me", "i'm blocking you", "im blocking you", "this is toxic",
    "you always do this", "you never listen", "leave me alone", "i'm so mad",
    "im so mad", "i hate you", "grow up", "shut it",
)

_BOREDOM_WORDS = (
    "dead chat", "chat's dead", "chats dead", "so bored", "im bored", "i'm bored",
    "nothing to do", "bruh dead ass silent", "anyone here", "chat dead",
)

_BANTER_MARKERS = ("lol", "lmao", "lmfao", "bro 💀", "💀", "😭😭", "ain't no way", "aint no way")

_CURIOSITY_WORDS = (
    "guess what", "you won't believe", "you wont believe", "so today", "funny story",
    "wait so", "ok so basically",
)


def _joined_recent_text(messages: list[MessageRecord], window: int = 6) -> str:
    return " \n ".join(m.content.lower() for m in messages[-window:] if m.content)


def _count_hits(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text)


def detect_sadness(messages: list[MessageRecord]) -> float:
    text = _joined_recent_text(messages, window=4)
    hits = _count_hits(text, _SADNESS_WORDS)
    if hits == 0:
        return 0.0
    return min(0.45 + 0.25 * hits, 1.0)


def detect_celebration(messages: list[MessageRecord]) -> float:
    text = _joined_recent_text(messages, window=4)
    hits = _count_hits(text, _CELEBRATION_WORDS)
    exclamations = text.count("!")
    if hits == 0 and exclamations < 3:
        return 0.0
    return min(0.35 + 0.2 * hits + 0.05 * exclamations, 1.0)


def detect_help_request(messages: list[MessageRecord]) -> float:
    if not messages:
        return 0.0
    latest = messages[-1].content.lower()
    hits = _count_hits(latest, _HELP_WORDS)
    ends_with_question = latest.strip().endswith("?")
    if hits == 0:
        return 0.25 if ends_with_question else 0.0
    return min(0.5 + 0.2 * hits + (0.1 if ends_with_question else 0), 1.0)


def detect_escalation(messages: list[MessageRecord]) -> float:
    """Safety-critical detector. Deliberately biased toward over-triggering -
    it's far better to stay quiet during a real argument than to jump in.
    """
    text = _joined_recent_text(messages, window=6)
    hits = _count_hits(text, _ESCALATION_WORDS)
    if hits == 0:
        return 0.0

    # Multiple distinct authors firing hostile language at each other is the
    # clearest signal of a real fight rather than one person venting.
    recent = messages[-6:]
    distinct_authors = len({m.user_id for m in recent if not m.is_bot})
    multiplier = 1.15 if distinct_authors >= 2 else 0.9

    return min(0.35 * hits * multiplier, 1.0)


def detect_boredom(messages: list[MessageRecord]) -> float:
    if len(messages) < 2 or messages[-1].is_attachment_only:
        return 0.0
    text = _joined_recent_text(messages, window=5)
    hits = _count_hits(text, _BOREDOM_WORDS)

    # A long silence followed by activity resuming is also a lull signal.
    gap = messages[-1].timestamp - messages[-2].timestamp if len(messages) >= 2 else 0
    long_gap = gap > 20 * 60

    if hits == 0 and not long_gap:
        return 0.0
    return min(0.3 * hits + (0.25 if long_gap else 0), 1.0)


def detect_banter(messages: list[MessageRecord]) -> float:
    text = _joined_recent_text(messages, window=4)
    hits = _count_hits(text, _BANTER_MARKERS)
    distinct_authors = len({m.user_id for m in messages[-4:] if not m.is_bot})
    if hits == 0 or distinct_authors < 2:
        return 0.0
    return min(0.25 + 0.15 * hits, 0.85)


def detect_curiosity(messages: list[MessageRecord]) -> float:
    """Signals a story/personal update worth engaging with out of genuine interest."""
    if not messages:
        return 0.0
    latest = messages[-1].content.lower()
    hits = _count_hits(latest, _CURIOSITY_WORDS)
    if hits == 0:
        return 0.0
    return min(0.3 + 0.2 * hits, 0.7)


TRIGGER_DETECTORS: dict[str, Callable[[list[MessageRecord]], float]] = {
    "sadness": detect_sadness,
    "celebration": detect_celebration,
    "help_request": detect_help_request,
    "boredom": detect_boredom,
    "banter": detect_banter,
    "curiosity": detect_curiosity,
}

TRIGGER_DESCRIPTIONS: dict[str, str] = {
    "sadness": "someone seems upset or down",
    "celebration": "someone's celebrating or hyped about something",
    "help_request": "someone's asking for help or stuck on something",
    "boredom": "the chat's dead or someone's bored",
    "banter": "there's a joke or banter going on worth joining",
    "curiosity": "someone shared something interesting worth reacting to",
    "get_to_know": "a chance to genuinely get to know someone in the chat you don't know much about yet",
    "escalation": "the conversation looks like it's escalating into an argument",
}


# --- Lightweight per-message vibe signal, used to update a user's rolling vibe profile ---

_CAPS_RE = re.compile(r"[A-Z]")
_ALPHA_RE = re.compile(r"[A-Za-z]")
_EMOJI_ISH_RE = re.compile(r"[!?]{2,}|[\U0001F300-\U0001FAFF]")


def instantaneous_vibe(content: str) -> tuple[float, float]:
    """Returns (energy, formality) signal for a single message, 0-1 each."""
    if not content.strip():
        return 0.5, 0.4

    alpha_count = len(_ALPHA_RE.findall(content))
    caps_count = len(_CAPS_RE.findall(content))
    caps_ratio = (caps_count / alpha_count) if alpha_count else 0.0
    emoji_hits = len(_EMOJI_ISH_RE.findall(content))
    exclamations = content.count("!")

    energy = min(0.3 + caps_ratio * 0.4 + 0.08 * emoji_hits + 0.05 * exclamations, 1.0)

    words = content.split()
    avg_word_len = sum(len(w) for w in words) / len(words) if words else 4
    has_proper_punct = bool(re.search(r"[.!?]$", content.strip()))
    slang_markers = _count_hits(content.lower(), ("lol", "lmao", "bro", "fr", "ngl", "tbh", "ong"))
    formality = max(0.15, min(0.3 + (avg_word_len - 4) * 0.05 + (0.15 if has_proper_punct else 0) - 0.05 * slang_markers, 1.0))

    return energy, formality
