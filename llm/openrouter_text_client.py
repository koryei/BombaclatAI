"""Bounded OpenRouter text fallback used when Gemini cannot answer."""

import asyncio
import base64
import json
import logging
import random
import time
import urllib.error
import urllib.request

import config
from core.agent_tools import openrouter_tool_schemas
from llm.gemini_client import AgentToolCall, AgentTurn, clean_response

logger = logging.getLogger(__name__)


class TextRateLimitError(Exception):
    def __init__(self, retry_after: float | None = None):
        super().__init__("openrouter text request was rate limited")
        self.retry_after = retry_after


class TextRequestError(Exception):
    pass


class OpenRouterTextClient:
    """OpenRouter text fallback with a short, bounded rate-limit retry loop."""

    def __init__(self):
        self.calls_made = 0
        self.calls_failed = 0
        self.rate_limit_retries = 0

    async def generate(
        self,
        prompt: str,
        *,
        images: list[tuple[str, bytes]] | None = None,
    ) -> str | None:
        if not config.OPENROUTER_API_KEY:
            logger.info("openrouter_text skipped api_key_configured=False")
            return None

        payload = self._build_payload(prompt, images=images)
        attempts = config.OPENROUTER_TEXT_MAX_RETRIES + 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response_text = await asyncio.wait_for(
                    asyncio.to_thread(self._call_sync, payload),
                    timeout=config.OPENROUTER_TEXT_TIMEOUT_SECONDS,
                )
                self.calls_made += 1
                logger.info(
                    "openrouter_text_call status=ok model=%s attempt=%s latency_ms=%.0f",
                    config.OPENROUTER_TEXT_MODEL,
                    attempt + 1,
                    (time.perf_counter() - started) * 1000,
                )
                return clean_response(response_text)
            except TextRateLimitError as exc:
                self.rate_limit_retries += 1
                if attempt >= attempts - 1:
                    self.calls_failed += 1
                    logger.warning(
                        "openrouter_text_call status=rate_limited model=%s attempts=%s",
                        config.OPENROUTER_TEXT_MODEL,
                        attempt + 1,
                    )
                    return None
                delay = exc.retry_after or config.OPENROUTER_TEXT_RETRY_BASE_SECONDS * (2**attempt)
                delay = min(max(delay, 0.5), config.OPENROUTER_TEXT_MAX_RETRY_DELAY_SECONDS)
                delay += random.uniform(0, 0.2)
                logger.info(
                    "openrouter_text_call status=rate_limited retry=%s delay_s=%.1f",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                self.calls_failed += 1
                logger.warning(
                    "openrouter_text_call status=timeout model=%s timeout_s=%s",
                    config.OPENROUTER_TEXT_MODEL,
                    config.OPENROUTER_TEXT_TIMEOUT_SECONDS,
                )
                return None
            except (TextRequestError, OSError, ValueError) as exc:
                self.calls_failed += 1
                logger.warning(
                    "openrouter_text_call status=failed model=%s error=%s",
                    config.OPENROUTER_TEXT_MODEL,
                    exc,
                )
                return None
            except Exception:
                self.calls_failed += 1
                logger.exception("openrouter_text_call status=unexpected")
                return None
        return None

    async def generate_with_tools(
        self,
        prompt: str,
        *,
        schemas: tuple[dict, ...] | None = None,
        images: list[tuple[str, bytes]] | None = None,
    ) -> AgentTurn | None:
        """Optional OpenRouter tool-call path for when Gemini is unavailable."""
        if not config.OPENROUTER_API_KEY:
            logger.info("openrouter_text skipped api_key_configured=False purpose=agent_tools")
            return None

        payload = self._build_tool_payload(prompt, schemas=schemas, images=images)
        attempts = config.OPENROUTER_TEXT_MAX_RETRIES + 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                data = await asyncio.wait_for(
                    asyncio.to_thread(self._call_sync_agent, payload),
                    timeout=config.OPENROUTER_TEXT_TIMEOUT_SECONDS,
                )
                self.calls_made += 1
                logger.info(
                    "openrouter_text_call status=ok purpose=agent_tools model=%s attempt=%s tool_calls=%s latency_ms=%.0f",
                    config.OPENROUTER_TEXT_MODEL,
                    attempt + 1,
                    len(data.tool_calls),
                    (time.perf_counter() - started) * 1000,
                )
                return data
            except TextRateLimitError as exc:
                self.rate_limit_retries += 1
                if attempt >= attempts - 1:
                    self.calls_failed += 1
                    logger.warning(
                        "openrouter_text_call status=rate_limited purpose=agent_tools model=%s attempts=%s",
                        config.OPENROUTER_TEXT_MODEL,
                        attempt + 1,
                    )
                    return None
                delay = exc.retry_after or config.OPENROUTER_TEXT_RETRY_BASE_SECONDS * (2**attempt)
                delay = min(max(delay, 0.5), config.OPENROUTER_TEXT_MAX_RETRY_DELAY_SECONDS)
                await asyncio.sleep(delay + random.uniform(0, 0.2))
            except (asyncio.TimeoutError, TextRequestError, OSError, ValueError) as exc:
                self.calls_failed += 1
                logger.warning(
                    "openrouter_text_call status=failed purpose=agent_tools model=%s error=%s",
                    config.OPENROUTER_TEXT_MODEL,
                    exc,
                )
                return None
            except Exception:
                self.calls_failed += 1
                logger.exception("openrouter_text_call status=unexpected purpose=agent_tools")
                return None
        return None

    @staticmethod
    def _multimodal_content(
        prompt: str,
        images: list[tuple[str, bytes]] | None = None,
    ):
        if not images:
            return prompt
        content: list[dict] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
                },
            }
            for mime_type, image_bytes in images
        )
        return content

    @staticmethod
    def _build_payload(
        prompt: str,
        *,
        images: list[tuple[str, bytes]] | None = None,
    ) -> bytes:
        payload = {
            "model": config.OPENROUTER_VISION_MODEL if images else config.OPENROUTER_TEXT_MODEL,
            "messages": [{"role": "user", "content": OpenRouterTextClient._multimodal_content(prompt, images)}],
            "max_tokens": config.MAX_RESPONSE_TOKENS,
            "temperature": 0.9,
        }
        return json.dumps(payload).encode("utf-8")

    @staticmethod
    def _build_tool_payload(
        prompt: str,
        *,
        schemas: tuple[dict, ...] | None = None,
        images: list[tuple[str, bytes]] | None = None,
    ) -> bytes:
        payload = {
            "model": config.OPENROUTER_VISION_MODEL if images else config.OPENROUTER_TEXT_MODEL,
            "messages": [{"role": "user", "content": OpenRouterTextClient._multimodal_content(prompt, images)}],
            "tools": openrouter_tool_schemas() if schemas is None else openrouter_tool_schemas(schemas),
            "tool_choice": "auto",
            "max_tokens": config.MAX_RESPONSE_TOKENS,
            "temperature": 0.7,
        }
        return json.dumps(payload).encode("utf-8")

    @staticmethod
    def _call_sync(payload: bytes) -> str:
        request = urllib.request.Request(
            config.OPENROUTER_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/bombaclat-ai",
                "X-Title": "BombaclatAI",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=config.OPENROUTER_TEXT_TIMEOUT_SECONDS
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
                raise TextRateLimitError(retry_after) from exc
            raise TextRequestError(f"http_status={exc.code}") from exc
        except urllib.error.URLError as exc:
            raise TextRequestError("network_error") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or choice.get("text")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TextRequestError("invalid_provider_response") from exc

        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise TextRequestError("empty_provider_response")
        return content

    @staticmethod
    def _call_sync_agent(payload: bytes) -> AgentTurn:
        request = urllib.request.Request(
            config.OPENROUTER_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/bombaclat-ai",
                "X-Title": "BombaclatAI",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=config.OPENROUTER_TEXT_TIMEOUT_SECONDS
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
                raise TextRateLimitError(retry_after) from exc
            raise TextRequestError(f"http_status={exc.code}") from exc
        except urllib.error.URLError as exc:
            raise TextRequestError("network_error") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls") or []
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TextRequestError("invalid_provider_response") from exc

        tool_calls: list[AgentToolCall] = []
        for raw_call in raw_tool_calls:
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function") or {}
            name = function.get("name")
            if not name:
                continue
            raw_arguments = function.get("arguments") or {}
            if isinstance(raw_arguments, str):
                try:
                    raw_arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    raw_arguments = {}
            if isinstance(raw_arguments, dict):
                tool_calls.append(AgentToolCall(str(name), raw_arguments))

        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str):
            content = ""
        return AgentTurn(clean_response(content) if content.strip() else None, tool_calls)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
