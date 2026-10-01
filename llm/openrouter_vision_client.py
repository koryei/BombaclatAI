"""Small OpenRouter multimodal client used only for explicit image requests."""

import asyncio
import base64
import json
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Optional

import config

logger = logging.getLogger(__name__)


class VisionRateLimitError(Exception):
    def __init__(self, retry_after: Optional[float] = None):
        super().__init__("openrouter vision request was rate limited")
        self.retry_after = retry_after


class VisionRequestError(Exception):
    pass


class OpenRouterVisionClient:
    """OpenRouter wrapper with bounded retries for provider rate limits.

    Image bytes are accepted only for the duration of a request. The client
    never logs image URLs, base64 data, or response bodies.
    """

    def __init__(self):
        self.calls_made = 0
        self.calls_failed = 0
        self.rate_limit_retries = 0

    async def generate_vision(
        self,
        prompt: str,
        images: list[tuple[str, bytes]],
    ) -> Optional[str]:
        if not config.VISION_ENABLED or not config.OPENROUTER_API_KEY:
            logger.info(
                "openrouter_vision skipped enabled=%s api_key_configured=%s",
                config.VISION_ENABLED,
                bool(config.OPENROUTER_API_KEY),
            )
            return None
        if not images:
            return None

        payload = self._build_payload(prompt, images)
        attempts = config.VISION_MAX_RETRIES + 1
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                response_text = await asyncio.wait_for(
                    asyncio.to_thread(self._call_sync, payload),
                    timeout=config.VISION_TIMEOUT_SECONDS,
                )
                self.calls_made += 1
                logger.info(
                    "openrouter_vision_call status=ok model=%s images=%s attempt=%s latency_ms=%.0f",
                    config.OPENROUTER_VISION_MODEL,
                    len(images),
                    attempt + 1,
                    (time.perf_counter() - started) * 1000,
                )
                return response_text
            except VisionRateLimitError as exc:
                self.rate_limit_retries += 1
                if attempt >= attempts - 1:
                    self.calls_failed += 1
                    logger.warning(
                        "openrouter_vision_call status=rate_limited model=%s attempts=%s",
                        config.OPENROUTER_VISION_MODEL,
                        attempt + 1,
                    )
                    return None
                delay = exc.retry_after or config.VISION_RETRY_BASE_SECONDS * (2**attempt)
                delay = min(max(delay, 0.5), config.VISION_MAX_RETRY_DELAY_SECONDS)
                delay += random.uniform(0, 0.25)
                logger.info(
                    "openrouter_vision_call status=rate_limited retry=%s delay_s=%.1f",
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except asyncio.TimeoutError:
                self.calls_failed += 1
                logger.warning(
                    "openrouter_vision_call status=timeout model=%s timeout_s=%s",
                    config.OPENROUTER_VISION_MODEL,
                    config.VISION_TIMEOUT_SECONDS,
                )
                return None
            except (VisionRequestError, OSError, ValueError) as exc:
                self.calls_failed += 1
                logger.warning(
                    "openrouter_vision_call status=failed model=%s error=%s",
                    config.OPENROUTER_VISION_MODEL,
                    exc,
                )
                return None
            except Exception:
                self.calls_failed += 1
                logger.exception("openrouter_vision_call status=unexpected")
                return None
        return None

    @staticmethod
    def _build_payload(prompt: str, images: list[tuple[str, bytes]]) -> bytes:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for mime_type, image_bytes in images:
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                }
            )

        payload = {
            "model": config.OPENROUTER_VISION_MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": config.VISION_MAX_OUTPUT_TOKENS,
            "temperature": 0.8,
            "reasoning": {"effort": "none", "exclude": True},
            "chat_template_kwargs": {"enable_thinking": False},
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
                request, timeout=config.VISION_TIMEOUT_SECONDS
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
                raise VisionRateLimitError(retry_after) from exc
            raise VisionRequestError(f"http_status={exc.code}") from exc
        except urllib.error.URLError as exc:
            raise VisionRequestError("network_error") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content")
            if not content:
                # Some OpenRouter-compatible providers return text at the
                # choice level even when the chat message content is empty.
                content = choice.get("text")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise VisionRequestError("invalid_provider_response") from exc

        if isinstance(content, list):
            content = " ".join(
                item.get("text", "") for item in content if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            reasoning_present = bool(message.get("reasoning") or message.get("reasoning_content"))
            finish_reason = choice.get("finish_reason", "unknown")
            raise VisionRequestError(
                f"empty_provider_response finish_reason={finish_reason} "
                f"reasoning_present={reasoning_present}"
            )
        return content


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
