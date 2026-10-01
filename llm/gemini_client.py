import asyncio
import logging
import random
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types

import config
from core.agent_tools import AGENT_TOOL_SCHEMAS

logger = logging.getLogger(__name__)

FALLBACKS = (
    "i fumbled that one, run it back in a sec",
    "that one got lost in the sauce, try me again",
    "my timing just died, give me a minute",
)
LEAK_MARKERS = (
    "system prompt",
    "critical behavior",
    "anti jailbreak",
    "as an ai",
    "language model",
    "conversation context",
    "output only",
    # A model sometimes writes a function call as prose instead of emitting a
    # native tool call. That text is internal plumbing and must never ship.
    "default_api",
    "declaration:",
    "tool_code",
    "search_public_web",
    "fetch_public_page",
    "search_recent_context",
    "get_recent_updates",
    "get_user_profile",
    "remember_fact",
    "react_to_message",
    "safe_calculator",
    "set_reminder",
    "cancel_reminder",
    "send_gif",
)
_ALLOWED_RESPONSE_EMOJIS = frozenset("😭💀🔥😂❤👍👎🎉✅❌👀🤔😤😎🤡🙄🥲😔⁉️\ufe0f")
_ALLOWED_RESPONSE_PUNCTUATION = frozenset("?'!@<>-_.,:/#%&=+()[]")


@dataclass
class AgentToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentTurn:
    text: str | None
    tool_calls: list[AgentToolCall]


class RollingRateLimiter:
    """Shared across every call type (persona replies + reasoning calls) so
    the process never exceeds the free-tier ceiling regardless of which
    feature is generating traffic."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self.timestamps: deque = deque(maxlen=limit)
        self.lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self.lock:
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] >= self.window_seconds:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.limit:
                return False
            self.timestamps.append(now)
            return True

    def current_usage(self) -> tuple[int, int]:
        """Synchronous, dashboard-safe snapshot of (requests used, limit).
        Doesn't prune expired timestamps to avoid touching the deque outside
        the lock; it's a live approximation, not a precise count."""
        now = time.monotonic()
        active = sum(1 for ts in self.timestamps if now - ts < self.window_seconds)
        return active, self.limit


class GeminiClient:
    def __init__(self):
        self.limiter = RollingRateLimiter(
            config.RATE_LIMIT_REQUESTS,
            config.RATE_LIMIT_WINDOW_SECONDS,
        )
        self.calls_made = 0
        self.calls_failed = 0

    async def generate_primary(
        self,
        prompt: str,
        *,
        images: list[tuple[str, bytes]] | None = None,
    ) -> str | None:
        """Primary Gemini reply path with optional native multimodal input."""
        text = await self._generate_raw(
            prompt,
            max_tokens=config.MAX_RESPONSE_TOKENS,
            temperature=0.9,
            purpose="reply",
            images=images,
        )
        if text is None:
            return None
        return clean_response(text)

    async def generate(self, prompt: str) -> str | None:
        """Persona-voiced reply generation with the legacy local fallback."""
        text = await self.generate_primary(prompt)
        return text if text is not None else random.choice(FALLBACKS)

    async def generate_with_tools(
        self,
        prompt: str,
        *,
        schemas: tuple[dict[str, Any], ...] | None = None,
        images: list[tuple[str, bytes]] | None = None,
    ) -> AgentTurn | None:
        """Ask Gemini for a response and optional native function calls.

        Automatic SDK execution is disabled deliberately. Bombaclat validates
        and executes every tool request itself so the model cannot bypass
        permissions, privacy checks, or rate limits.
        """
        if not await self.limiter.acquire():
            logger.info("Local Gemini rate limit reached purpose=agent_tools")
            return None

        tool_schemas = schemas or AGENT_TOOL_SCHEMAS
        declarations = [
            types.FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters_json_schema=schema["parameters"],
            )
            for schema in tool_schemas
        ]
        gen_config = types.GenerateContentConfig(
            max_output_tokens=config.MAX_RESPONSE_TOKENS,
            temperature=0.7,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),  # type: ignore[call-arg]
        )
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_sync, prompt, gen_config, images),
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            self.calls_made += 1
            turn = self._parse_agent_turn(response)
            logger.info(
                "gemini_call purpose=agent_tools status=ok tool_calls=%s latency_ms=%.0f",
                len(turn.tool_calls),
                (time.perf_counter() - started) * 1000,
            )
            return turn
        except asyncio.TimeoutError:
            self.calls_failed += 1
            logger.warning("gemini_call purpose=agent_tools status=timeout")
            return None
        except (errors.APIError, OSError, ValueError) as exc:
            self.calls_failed += 1
            logger.warning("gemini_call purpose=agent_tools status=failed error=%s", exc)
            return None
        except Exception:
            self.calls_failed += 1
            logger.exception("gemini_call purpose=agent_tools status=unexpected")
            return None

    @staticmethod
    def _parse_agent_turn(response) -> AgentTurn:
        text_parts: list[str] = []
        tool_calls: list[AgentToolCall] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                function_call = getattr(part, "function_call", None)
                if function_call is not None:
                    name = getattr(function_call, "name", None)
                    if name:
                        raw_args = getattr(function_call, "args", None) or {}
                        tool_calls.append(AgentToolCall(str(name), dict(raw_args)))
                    continue
                part_text = getattr(part, "text", None)
                if part_text:
                    text_parts.append(str(part_text))
        text = " ".join(text_parts).strip()
        return AgentTurn(clean_response(text) if text else None, tool_calls)

    async def generate_reasoning(self, prompt: str) -> str | None:
        """Small, structured call used by the decision engine to reason about
        edge cases. Shares the same rate limiter and safety net as generate()."""
        return await self._generate_raw(
            prompt,
            max_tokens=config.MAX_REASONING_TOKENS,
            temperature=0.4,
            purpose="reasoning",
        )

    async def _generate_raw(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        purpose: str,
        images: list[tuple[str, bytes]] | None = None,
    ) -> str | None:
        if not await self.limiter.acquire():
            logger.info("Local Gemini rate limit reached")
            return None

        gen_config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),  # type: ignore[call-arg]
        )

        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._call_sync, prompt, gen_config, images),
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            self.calls_made += 1
            logger.info(
                "gemini_call purpose=%s status=ok latency_ms=%.0f",
                purpose,
                (time.perf_counter() - started) * 1000,
            )
            text = response.text
            return text if text and text.strip() else None
        except asyncio.TimeoutError:
            self.calls_failed += 1
            logger.warning(
                "gemini_call purpose=%s status=timeout latency_ms=%.0f timeout_s=%s",
                purpose,
                (time.perf_counter() - started) * 1000,
                config.REQUEST_TIMEOUT_SECONDS,
            )
            return None
        except (errors.APIError, OSError, ValueError) as exc:
            self.calls_failed += 1
            logger.warning(
                "gemini_call purpose=%s status=failed latency_ms=%.0f error=%s",
                purpose,
                (time.perf_counter() - started) * 1000,
                exc,
            )
            return None
        except Exception:
            # Last-resort net: a bad response from the API should never crash
            # the event loop or an autonomous background task.
            self.calls_failed += 1
            logger.exception(
                "gemini_call purpose=%s status=unexpected latency_ms=%.0f",
                purpose,
                (time.perf_counter() - started) * 1000,
            )
            return None

    @staticmethod
    def _build_contents(
        prompt: str,
        images: list[tuple[str, bytes]] | None = None,
    ):
        if not images:
            return prompt
        parts = [types.Part.from_text(text=prompt)]
        parts.extend(
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            for mime_type, image_bytes in images
        )
        return types.Content(role="user", parts=parts)

    def _call_sync(
        self,
        prompt: str,
        gen_config: types.GenerateContentConfig,
        images: list[tuple[str, bytes]] | None = None,
    ):
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        return client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=self._build_contents(prompt, images),
            config=gen_config,
        )


def clean_response(text: str) -> str:
    # Normalize long dash punctuation before the final persona sanitizer so the
    # generated reply cannot contain the forbidden punctuation.
    text = (
        text.strip()
        .strip('"')
        .replace("\u2014", ", ")
        .replace("\u2013", "-")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    text = re.sub(r"^(bombaclat|assistant)\s*:\s*", "", text, flags=re.IGNORECASE)
    # Discord does not reliably render Markdown link syntax, and models may
    # repeat a URL as both the label and target. Keep the actual target once.
    text = re.sub(
        r"\[[^\]]*\]\(\s*(https?://[^)\s]+)\s*\)",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    if not text or any(marker in text.lower() for marker in LEAK_MARKERS):
        return random.choice(FALLBACKS)

    text = text.lower()
    text = "".join(
        character
        for character in text
        if character.isalnum()
        or character.isspace()
        or character in _ALLOWED_RESPONSE_PUNCTUATION
        or character in _ALLOWED_RESPONSE_EMOJIS
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500].rsplit(" ", 1)[0] if len(text) > 500 else text
