"""Safe memory storage, legacy extraction, and context-aware recall.

When native agent tooling is enabled, semantic fact selection happens through
validated model tool calls. The pattern extractor in this module remains the
explicit fallback when agent tooling is disabled. Sensitive facts (breakups,
mental health, drama) are flagged so they're never casually surfaced in front
of the wrong audience, even if they're technically "known".
"""

import logging
import re

from core.models import MemoryCandidate
from db.repository import Repository

logger = logging.getLogger(__name__)

_FACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bi love ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi really like ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi like ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi enjoy ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi'?m (?:really |super |kinda |low key )?into ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi hate ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "dislike"),
    (re.compile(r"\bi can'?t stand ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "dislike"),
    (re.compile(r"\bi'?m (?:so |really )?scared of ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bmy favorite ([a-z0-9 ]{3,25}) is ([a-z0-9 ]{2,30})\b", re.IGNORECASE), "preference"),
    (re.compile(r"\bi just (got|bought|finished|started|beat|won|lost|adopted) ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "event"),
    (re.compile(r"\bi(?:'m| am) (?:currently )?(playing|watching|reading|listening to) ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi(?:'m| am) learning ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi (?:usually )?play ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi main ([a-z0-9 &'_-]{2,30})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi(?:'ve| have) been playing ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi listen to ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi watch ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "interest"),
    (re.compile(r"\bi(?:'m| am) from ([a-z0-9 &'_-]{3,30})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\b(?:call me|i go by|my name is) ([a-z0-9 _'-]{2,30})\b", re.IGNORECASE), "identity"),
    (re.compile(r"\bi prefer ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "preference"),
    (re.compile(r"\bi do(?:n't| not) like ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "dislike"),
    (re.compile(r"\bi(?:'m| am) trying to ([a-z0-9 &'_-]{3,40})\b", re.IGNORECASE), "goal"),
    (re.compile(r"\bmy birthday is ([a-z0-9 ,]{3,30})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi work (?:at|as) ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi live in ([a-z0-9 ]{3,30})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi study ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi go to ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi have a (dog|cat|brother|sister|girlfriend|boyfriend|gf|bf)\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bmy (dog|cat|pet)(?:'s name)? is ([a-z0-9 ]{2,20})\b", re.IGNORECASE), "fact"),
    (re.compile(r"\bi want to ([a-z0-9 ]{3,40})\b", re.IGNORECASE), "goal"),
]

_CONTEXTUAL_ENDORSEMENT_RE = re.compile(
    r"\b(?P<subject>[a-z0-9][a-z0-9 &'_-]{1,50}?)\s+is\s+"
    r"(?:(?:a|an|the)\s+)?"
    r"(?:(?:really|so|super|actually)\s+)?"
    r"(?:goated|great|amazing|fire|awesome|sick|good)"
    r"(?:\s+(?:singer|artist|band|group|song|album|game|show|movie|rapper|creator|producer))?"
    r"(?:\s+(?:dude|guy|person))?\b.*?"
    r"\bi\s+(?:love|like)\s+(?:that|this)\s+"
    r"(?:dude|guy|person|singer|artist|rapper|creator|producer)\b",
    re.IGNORECASE,
)
_DISCOURSE_FILLERS = {
    "yo", "lowk", "lowkey", "bro", "bruh", "ngl", "fr", "tbh", "honestly", "deadass",
}
_VAGUE_INTEREST_RE = re.compile(
    r"\b(?:love|like|enjoy)\s+(?:that|this|it|them)\b", re.IGNORECASE
)


_SENSITIVE_MARKERS = (
    "breakup", "broke up", "depress", "suicid", "self harm", "self-harm",
    "cheated", "cheating", "hate him", "hate her", "hate myself", "hate my self",
    "i hate my life", "i hate everyone", "fight with", "drama", "abuse", "therapy",
    "therapist", "diagnosed", "panic attack", "anxiety attack",
)

_TRANSIENT_EMOTIONAL_MARKERS = (
    "i hate myself", "i hate my self", "i hate my life", "i hate everyone",
    "i'm done", "im done", "i give up", "nobody cares", "no one cares",
)

_MAX_CANDIDATES_PER_MESSAGE = 2


def _is_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def extract_facts(
    user_id: int,
    content: str,
    guild_id: int | None,
    channel_id: int | None = None,
    is_private_dm: bool = False,
    source_message_id: int | None = None,
) -> list[MemoryCandidate]:
    if not content or len(content) < 6:
        return []

    candidates: list[MemoryCandidate] = []
    lowered_content = content.strip()
    lowered_for_safety = lowered_content.lower()
    is_transient_emotion = any(
        marker in lowered_for_safety for marker in _TRANSIENT_EMOTIONAL_MARKERS
    )

    contextual_match = _CONTEXTUAL_ENDORSEMENT_RE.search(lowered_content)
    if contextual_match and not is_transient_emotion:
        subject_words = contextual_match.group("subject").strip().lower().split()
        while subject_words and subject_words[0] in _DISCOURSE_FILLERS:
            subject_words.pop(0)
        subject = " ".join(subject_words)
        if subject:
            candidates.append(
                MemoryCandidate(
                    about_user_id=user_id,
                    memory_text=f"likes {subject}",
                    category="interest",
                    confidence=0.75,
                    is_sensitive=_is_sensitive(content),
                    guild_id=guild_id,
                    source_channel_id=channel_id,
                    source_is_private_dm=is_private_dm,
                    source_message_id=source_message_id,
                )
            )

    for pattern, category in _FACT_PATTERNS:
        match = pattern.search(lowered_content)
        if not match:
            continue
        # Venting should influence the current tone, not become a permanent
        # preference that can be recalled months later.
        if is_transient_emotion:
            continue
        fact_text = match.group(0).strip().lower()
        fact_text = re.sub(r"\s+", " ", fact_text)[:150]
        if _VAGUE_INTEREST_RE.search(fact_text):
            continue
        if any(existing.memory_text == fact_text for existing in candidates):
            continue
        sensitive = _is_sensitive(content)
        candidates.append(
            MemoryCandidate(
                about_user_id=user_id,
                memory_text=fact_text,
                category=category,
                confidence=0.6,
                is_sensitive=sensitive,
                guild_id=guild_id,
                source_channel_id=channel_id,
                source_is_private_dm=is_private_dm,
                source_message_id=source_message_id,
            )
        )
        if len(candidates) >= _MAX_CANDIDATES_PER_MESSAGE:
            break

    return candidates


async def store_new_facts(repo: Repository, candidates: list[MemoryCandidate]) -> int:
    stored = 0
    for candidate in candidates:
        if await repo.is_duplicate_memory(candidate.about_user_id, candidate.memory_text):
            continue
        await repo.add_memory(candidate)
        stored += 1
        if candidate.is_sensitive:
            logger.info(
                "Learned a sensitive memory about user %s in channel %s",
                candidate.about_user_id,
                candidate.source_channel_id,
            )
        else:
            logger.info("Learned about user %s: %s", candidate.about_user_id, candidate.memory_text)
    return stored


async def get_context_memories(
    repo: Repository,
    user_ids: list[int],
    is_dm: bool,
    channel_id: int | None = None,
    limit_per_user: int = 2,
) -> str:
    """Formats a short block of relevant, safe-to-share memories for the prompt.

    Sensitive memories are only ever surfaced in a direct DM with the person
    they're about - never in a group setting where they could be broadcast
    to people who shouldn't see them.
    """
    lines: list[str] = []
    for user_id in user_ids:
        memories = await repo.get_context_memories(
            user_id,
            is_private_dm=is_dm,
            channel_id=channel_id,
            limit=limit_per_user,
        )
        for stored_memory in memories:
            lines.append(f"- {stored_memory['memory_text']}")
    return "\n".join(lines[:6])
