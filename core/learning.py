"""The bot's self-evolution loop.

This isn't a neural net - it's a transparent, explainable reinforcement
system: every trigger type (sadness, celebration, help_request, ...) has a
learned weight that starts at 1.0. When the owner approves a decision tied
to a trigger, that trigger's weight nudges up (the bot leans into it more
next time). When rejected, it nudges down. Organic engagement (people
replying/reacting after an autonomous post) works the same way as a weaker,
automatic signal when the owner doesn't explicitly weigh in.

Weights are clamped to [0.15, 2.0] so no single trigger can be silenced
entirely or take over completely - the bot always keeps a little bit of
everything in play.
"""

import logging
import time

from core.models import UserVibe
from core.triggers import instantaneous_vibe
from db.repository import Repository

logger = logging.getLogger(__name__)

MIN_WEIGHT = 0.15
MAX_WEIGHT = 2.0
APPROVE_STEP = 0.08
REJECT_STEP = 0.12
ENGAGEMENT_STEP = 0.04

# Vibe updates are an exponential moving average so one wild message doesn't
# swing someone's whole profile.
VIBE_EMA_ALPHA = 0.2


class LearningEngine:
    def __init__(self, repo: Repository):
        self.repo = repo

    async def get_weight(self, trigger_type: str) -> float:
        return await self.repo.get_trigger_weight(trigger_type)

    async def reinforce(self, trigger_type: str, positive: bool, magnitude: float = 1.0) -> float:
        row = await self.repo.db.fetchone(
            "SELECT weight, success_count, failure_count FROM trigger_weights WHERE trigger_type = ?",
            (trigger_type,),
        )
        weight = row["weight"] if row else 1.0
        success = row["success_count"] if row else 0
        failure = row["failure_count"] if row else 0

        if positive:
            weight = min(weight * (1 + APPROVE_STEP * magnitude), MAX_WEIGHT)
            success += 1
        else:
            weight = max(weight * (1 - REJECT_STEP * magnitude), MIN_WEIGHT)
            failure += 1

        await self.repo.set_trigger_weight(trigger_type, weight, success, failure)
        logger.info(
            "Learning: trigger=%s positive=%s new_weight=%.3f (success=%d, failure=%d)",
            trigger_type, positive, weight, success, failure,
        )
        return weight

    async def reinforce_from_engagement(self, trigger_type: str, engaged: bool) -> None:
        """Weaker, automatic signal from organic replies/reactions after an
        unsolicited post, used only when the owner hasn't given explicit feedback."""
        await self.reinforce(trigger_type, positive=engaged, magnitude=ENGAGEMENT_STEP / APPROVE_STEP)

    async def update_vibe_from_message(self, user_id: int, content: str) -> UserVibe:
        instant_energy, instant_formality = instantaneous_vibe(content)
        existing = await self.repo.get_user(user_id)

        if existing is None:
            energy, formality = instant_energy, instant_formality
        else:
            energy = existing.energy + VIBE_EMA_ALPHA * (instant_energy - existing.energy)
            formality = existing.formality + VIBE_EMA_ALPHA * (instant_formality - existing.formality)

        await self.repo.update_user_vibe(user_id, energy, formality)
        return UserVibe(user_id=user_id, energy=energy, formality=formality)
