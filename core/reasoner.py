"""Fallback LLM judgment for autonomous decisions.

The native autonomous planner handles normal provider-backed decisions. This
reasoner remains the transparent, structured fallback when native planning is
unavailable or disabled; it stays rate-limited, timeout-protected, and logs a
short explanation for the resulting decision.
"""

import logging
import re

from llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

_REASONER_TEMPLATE = """you are the decision-making part of bombaclat's brain, a discord friend-group bot. \
you are not writing the reply itself, you're deciding whether bombaclat should jump into this \
conversation unprompted right now.

conversation so far:
{transcript}

possible reason to jump in: {trigger_hint}

decide if bombaclat should send a message right now. a real friend wouldn't jump into every \
conversation - only when it's genuinely warranted (someone needs support, a laugh, help, or hype). \
if it's not warranted, or the moment already passed, or it would feel intrusive, say no.

respond in exactly this format, nothing else:
DECISION: yes or no
REASON: one short casual sentence explaining why, lowercase, no punctuation drama
"""

_DECISION_RE = re.compile(r"DECISION:\s*(yes|no)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*(.+)", re.IGNORECASE)


class Reasoner:
    def __init__(self, gemini_client: GeminiClient):
        self.client = gemini_client

    async def decide(self, transcript: str, trigger_hint: str) -> tuple[bool, str]:
        prompt = _REASONER_TEMPLATE.format(transcript=transcript, trigger_hint=trigger_hint)
        raw = await self.client.generate_reasoning(prompt)

        if not raw:
            return False, "couldn't reach a verdict in time, defaulting to staying quiet"

        decision_match = _DECISION_RE.search(raw)
        reason_match = _REASON_RE.search(raw)

        should_post = bool(decision_match and decision_match.group(1).lower() == "yes")
        reason = reason_match.group(1).strip()[:200] if reason_match else "no clear reasoning returned"

        return should_post, reason
