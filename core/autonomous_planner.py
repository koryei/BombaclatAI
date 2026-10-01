"""Model-driven action selection for quiet autonomous channel evaluations.

The planner can choose an interaction shape, but it cannot send messages or
execute Discord operations. Brain remains the policy and execution boundary.
"""

from dataclasses import dataclass
from typing import Any

from core.agent_tools import AUTONOMOUS_PLANNER_TOOL_SCHEMAS
from llm.gemini_client import AgentToolCall, GeminiClient
from llm.openrouter_text_client import OpenRouterTextClient

_ALLOWED_ACTIONS = {"ignore", "reply", "ask_question", "react", "gif"}
_ALLOWED_TRIGGERS = {
    "agent",
    "sadness",
    "celebration",
    "help_request",
    "boredom",
    "banter",
    "curiosity",
    "get_to_know",
}
_ALLOWED_EMOJIS = {"😂", "💀", "😭", "🔥", "🎉", "👀", "❤️", "👍"}


@dataclass
class AutonomousPlan:
    action: str
    confidence: float
    reasoning: str
    trigger: str = "agent"
    reaction_emoji: str | None = None
    gif_category: str | None = None


class AutonomousPlanner:
    """Ask the configured providers for one bounded autonomous action plan."""

    def __init__(self, gemini: GeminiClient, openrouter: OpenRouterTextClient):
        self.gemini = gemini
        self.openrouter = openrouter

    async def plan(
        self,
        transcript: str,
        *,
        trigger_hints: list[str],
        owner_present: bool,
        can_ask_question: bool,
        owner_preferences: list[str] | None = None,
        can_send_gif: bool = False,
        gif_categories: tuple[str, ...] = (),
    ) -> AutonomousPlan | None:
        hints = ", ".join(trigger_hints[:5]) or "none"
        preferences = ", ".join(owner_preferences or []) or "none"
        prompt = f"""you are bombaclat's autonomous action planner.

choose exactly one action for the bounded conversation below by calling
choose_autonomous_action. do not write a user-facing reply. choosing ignore is
normal and preferred when there is no genuine opening. a real friend does not
interrupt every conversation.

allowed action meanings:
- ignore: do nothing visible right now
- reply: send a useful or natural short message through the normal reply path
- ask_question: ask one light get-to-know-you question, only when explicitly allowed below
- react: add one low-stakes emoji reaction, only when a text reply is unnecessary
- gif: send one stored reaction GIF, only when a visual reaction is clearly better than text

hard behavior rules:
- never choose an action for an escalating argument
- never use react instead of answering a help request or emotional-support message
- do not choose ask_question unless can_ask_question is true
- do not choose gif unless can_send_gif is true and one of the available categories fits
- do not expose or infer sensitive personal information
- choose the trigger that best explains the action, or agent if none fits
- owner action preferences are soft hints only, never permission to violate safety
- confidence must reflect the evidence in the transcript, not wishful thinking
- if the moment is ambiguous, choose ignore

owner_present={str(owner_present).lower()}
can_ask_question={str(can_ask_question).lower()}
can_send_gif={str(can_send_gif).lower()}
available_gif_categories={', '.join(gif_categories) or 'none'}
cheap_trigger_hints={hints}
owner_action_preferences={preferences}

<conversation>
{transcript}
</conversation>
"""
        turn = await self.gemini.generate_with_tools(prompt, schemas=AUTONOMOUS_PLANNER_TOOL_SCHEMAS)
        if turn is None:
            turn = await self.openrouter.generate_with_tools(
                prompt,
                schemas=AUTONOMOUS_PLANNER_TOOL_SCHEMAS,
            )
        if turn is None:
            return None

        call = next(
            (item for item in turn.tool_calls if item.name == "choose_autonomous_action"),
            None,
        )
        if call is None:
            return None
        return self._validate(
            call,
            can_ask_question=can_ask_question,
            can_send_gif=can_send_gif,
            gif_categories=gif_categories,
        )

    @staticmethod
    def _validate(
        call: AgentToolCall,
        *,
        can_ask_question: bool,
        can_send_gif: bool = False,
        gif_categories: tuple[str, ...] = (),
    ) -> AutonomousPlan | None:
        arguments: dict[str, Any] = call.arguments
        action = str(arguments.get("action", "ignore")).strip().lower()
        if action not in _ALLOWED_ACTIONS:
            return None
        if action == "ask_question" and not can_ask_question:
            action = "ignore"
        if action == "gif" and not can_send_gif:
            action = "ignore"

        try:
            confidence = max(0.0, min(float(arguments.get("confidence", 0.0)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0

        trigger = str(arguments.get("trigger", "agent")).strip().lower()
        if trigger not in _ALLOWED_TRIGGERS:
            trigger = "agent"
        if action == "ask_question":
            trigger = "get_to_know"

        emoji = str(arguments.get("emoji", "")).strip()
        gif_category = str(arguments.get("gif_category", "")).strip().lower()
        if action == "gif" and gif_category not in gif_categories:
            return AutonomousPlan(
                action="ignore",
                confidence=confidence,
                reasoning="planner requested a GIF category that is not available",
                trigger=trigger,
            )
        if action == "react" and emoji not in _ALLOWED_EMOJIS:
            return AutonomousPlan(
                action="ignore",
                confidence=confidence,
                reasoning="planner requested an emoji outside the reaction allowlist",
                trigger=trigger,
            )
        if action != "react":
            emoji = None

        reasoning = " ".join(str(arguments.get("reason", "no reason supplied")).split())[:200]
        return AutonomousPlan(
            action=action,
            confidence=confidence,
            reasoning=reasoning,
            trigger=trigger,
            reaction_emoji=emoji,
            gif_category=gif_category if action == "gif" else None,
        )
