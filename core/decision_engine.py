"""The core "should I say something right now" logic.

Flow per evaluation:
1. Escalation check first, always - this is a hard safety rule and is never
   overridden by learned weights or a model plan.
2. Run cheap trigger detectors as context hints and preserve learned weights
   for the provider-outage fallback path.
3. Let the bounded native planner choose ignore, reply, question, or reaction.
4. Validate confidence and action-specific safety gates before execution.
5. If planning is unavailable, use the learned-trigger/reasoner fallback.
"""

import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import cast

import config
from core.autonomous_planner import AutonomousPlanner
from core.learning import LearningEngine
from core.models import Decision, MessageRecord
from core.reasoner import Reasoner
from core.triggers import (
    TRIGGER_DESCRIPTIONS,
    TRIGGER_DETECTORS,
    detect_escalation,
    detect_help_request,
    detect_sadness,
)

logger = logging.getLogger(__name__)


def format_transcript(messages: list[MessageRecord]) -> str:
    return "\n".join(
        f"[{time.strftime('%H:%M:%S', time.localtime(m.timestamp))}] "
        f"[{m.author_name}]: {m.content}"
        for m in messages
    )


class DecisionEngine:
    def __init__(
        self,
        learning: LearningEngine,
        reasoner: Reasoner,
        planner: AutonomousPlanner | None = None,
    ):
        self.learning = learning
        self.reasoner = reasoner
        self.planner = planner

    async def evaluate(
        self,
        messages: list[MessageRecord],
        owner_present: bool,
        can_send_gif: bool = False,
        gif_categories: tuple[str, ...] = (),
    ) -> Decision:
        if not messages:
            return Decision(should_post=False, trigger=None, confidence=0.0, reasoning="no recent messages")

        escalation_score = detect_escalation(messages)
        if escalation_score >= config.ESCALATION_HARD_BLOCK_THRESHOLD:
            return Decision(
                should_post=False,
                trigger="escalation",
                confidence=escalation_score,
                reasoning="conversation looks heated, staying out of it",
            )

        candidates: list[tuple[str, float]] = []
        for trigger_name, detector in TRIGGER_DETECTORS.items():
            raw_score = detector(messages)
            if raw_score <= 0.0:
                continue
            weight = await self.learning.get_weight(trigger_name)
            confidence = min(raw_score * weight, 1.0)
            if owner_present:
                confidence = min(confidence + config.OWNER_CONFIDENCE_BOOST, 1.0)
            candidates.append((trigger_name, confidence))

        new_person_signal = await self._detect_get_to_know(messages)
        if new_person_signal is not None:
            trigger_name, raw_score = new_person_signal
            weight = await self.learning.get_weight(trigger_name)
            confidence = min(raw_score * weight, 1.0)
            if owner_present:
                confidence = min(confidence + config.OWNER_CONFIDENCE_BOOST, 1.0)
            candidates.append((trigger_name, confidence))

        trigger_hints = [
            f"{name}: {TRIGGER_DESCRIPTIONS.get(name, name)} (confidence {confidence:.2f})"
            for name, confidence in sorted(candidates, key=lambda pair: pair[1], reverse=True)
        ]
        can_ask_question = any(name == "get_to_know" for name, _ in candidates)
        if (
            config.AUTONOMY_MODE == "autonomous"
            and config.AUTONOMOUS_PLANNER_ENABLED
            and self.planner is not None
        ):
            owner_preferences = []
            get_config = cast(
                Callable[[str], Awaitable[str | None]] | None,
                getattr(self.learning.repo, "get_config", None),
            )
            if callable(get_config):
                preference_names = {trigger_name for trigger_name, _ in candidates}
                preference_names.add("agent")
                for trigger_name in sorted(preference_names):
                    preference = await get_config(f"OWNER_ACTION_PREFERENCE_{trigger_name}")
                    if preference:
                        owner_preferences.append(f"{trigger_name} -> {preference}")
            planner_kwargs = {
                "trigger_hints": trigger_hints,
                "owner_present": owner_present,
                "can_ask_question": can_ask_question,
                "owner_preferences": owner_preferences,
            }
            if can_send_gif:
                planner_kwargs["can_send_gif"] = True
                planner_kwargs["gif_categories"] = gif_categories
            plan = await self.planner.plan(format_transcript(messages), **planner_kwargs)
            if plan is not None:
                return self._decision_from_plan(
                    plan,
                    messages,
                    can_send_gif=can_send_gif,
                )

        if not candidates:
            return Decision(should_post=False, trigger=None, confidence=0.0, reasoning="nothing worth jumping into")

        trigger, confidence = max(candidates, key=lambda pair: pair[1])

        description = TRIGGER_DESCRIPTIONS.get(trigger, trigger)

        reaction_emoji = self._choose_reaction(trigger, confidence, messages)
        if reaction_emoji is not None:
            return Decision(
                should_post=True,
                trigger=trigger,
                confidence=confidence,
                reasoning=f"{description} (light reaction)",
                action_type="reaction",
                reaction_emoji=reaction_emoji,
            )

        if confidence >= config.AUTONOMOUS_POST_THRESHOLD:
            return Decision(
                should_post=True,
                trigger=trigger,
                confidence=confidence,
                reasoning=f"{description} (high confidence)",
            )

        if confidence >= config.AUTONOMOUS_REASONING_THRESHOLD:
            transcript = format_transcript(messages)
            should_post, reason = await self.reasoner.decide(transcript, description)
            return Decision(should_post=should_post, trigger=trigger, confidence=confidence, reasoning=reason)

        return Decision(
            should_post=False,
            trigger=trigger,
            confidence=confidence,
            reasoning="confidence too low to act on",
        )

    @staticmethod
    def _decision_from_plan(
        plan,
        messages: list[MessageRecord],
        *,
        can_send_gif: bool = False,
    ) -> Decision:
        """Convert a model plan into an action while retaining hard policy gates."""
        action = plan.action
        trigger = plan.trigger or "agent"
        confidence = plan.confidence
        reasoning = plan.reasoning or "no reason supplied"

        if confidence < config.AUTONOMOUS_REASONING_THRESHOLD and action != "ignore":
            return Decision(
                should_post=False,
                trigger=trigger,
                confidence=confidence,
                reasoning="planner confidence was below the autonomous action threshold",
            )

        if action == "react":
            if (
                confidence < config.REACTION_MIN_CONFIDENCE
                or detect_help_request(messages) >= 0.5
                or detect_sadness(messages) >= 0.45
                or not config.REACTIONS_ENABLED
            ):
                return Decision(
                    should_post=False,
                    trigger=trigger,
                    confidence=confidence,
                    reasoning="reaction blocked by help, support, confidence, or reaction policy",
                )
            return Decision(
                should_post=True,
                trigger=trigger,
                confidence=confidence,
                reasoning=reasoning,
                action_type="reaction",
                reaction_emoji=plan.reaction_emoji,
            )

        if action == "gif":
            if (
                not can_send_gif
                or confidence < config.REACTION_MIN_CONFIDENCE
                or detect_help_request(messages) >= 0.5
                or detect_sadness(messages) >= 0.45
                or not config.GIFS_ENABLED
            ):
                return Decision(
                    should_post=False,
                    trigger=trigger,
                    confidence=confidence,
                    reasoning="GIF blocked by availability, support, confidence, or GIF policy",
                )
            return Decision(
                should_post=True,
                trigger=trigger,
                confidence=confidence,
                reasoning=reasoning,
                action_type="gif",
                gif_category=plan.gif_category,
            )

        if action in {"reply", "ask_question"}:
            if action == "reply" and detect_help_request(messages) >= 0.5:
                trigger = "help_request"
            elif action == "reply" and detect_sadness(messages) >= 0.45 and trigger == "agent":
                trigger = "sadness"
            return Decision(
                should_post=True,
                trigger=trigger,
                confidence=confidence,
                reasoning=reasoning,
                action_type="text",
            )

        return Decision(
            should_post=False,
            trigger=trigger,
            confidence=confidence,
            reasoning=reasoning,
        )

    async def _detect_get_to_know(self, messages: list[MessageRecord]) -> tuple[str, float] | None:
        """Signals a chance to genuinely get to know someone the bot barely
        knows yet - part of actively learning its environment rather than
        only reacting to strong emotional cues."""
        latest = messages[-1]
        if latest.is_bot or latest.is_command or latest.is_attachment_only:
            return None

        recent_window = messages[-8:]
        user_message_count = sum(1 for m in recent_window if m.user_id == latest.user_id)
        if user_message_count < 2:
            return None  # don't interrogate someone after a single one-off message

        if any(m.is_bot for m in recent_window[-2:]):
            return None  # let the existing exchange breathe before asking a question

        channel_id = latest.channel_id
        if channel_id is None or not await self.learning.repo.curiosity_allowed(
            latest.user_id, channel_id, config.GET_TO_KNOW_COOLDOWN_SECONDS
        ):
            return None

        settings = await self.learning.repo.get_channel_settings(channel_id)
        is_private_dm = bool(settings and settings["is_private_dm"])
        existing_memories = await self.learning.repo.get_context_memories(
            latest.user_id,
            is_private_dm=is_private_dm,
            channel_id=channel_id,
            limit=1,
        )
        if existing_memories:
            return None  # already knows something safe in this context

        # This sits just above the reasoner threshold so the bot can actually
        # ask a light question instead of silently declining every opportunity.
        return ("get_to_know", config.GET_TO_KNOW_SIGNAL)

    @staticmethod
    def _choose_reaction(
        trigger: str,
        confidence: float,
        messages: list[MessageRecord],
    ) -> str | None:
        if not config.REACTIONS_ENABLED or confidence < config.REACTION_MIN_CONFIDENCE:
            return None
        if trigger not in {"celebration", "banter", "boredom"}:
            return None
        latest = messages[-1]
        if latest.is_bot or latest.is_command or latest.is_attachment_only:
            return None
        if random.random() >= config.REACTION_PROBABILITY:
            return None
        options = {
            "celebration": ("🎉", "🔥", "😭"),
            "banter": ("😂", "💀", "😭"),
            "boredom": ("👀", "😭"),
        }
        return random.choice(options[trigger])
