"""
OmniRoute — Cloud Text Inference (Groq API).

Uses Groq's OpenAI-compatible endpoint for ultra-fast LLM inference.
Includes exponential backoff retry for rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from openai import OpenAI

logger = logging.getLogger("omniroute.inference.cloud_text")

_client: OpenAI | None = None
_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Retry config for rate limits
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set")
        _client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
        )
        logger.info("Groq text client initialized (model=%s)", _model)
    return _client


async def generate(prompt: str) -> tuple[str, float]:
    """
    Send a text prompt to Groq and return (response_text, latency_ms).
    Retries with exponential backoff on rate-limit (429) errors.
    """
    client = _get_client()

    for attempt in range(MAX_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            response = client.chat.completions.create(
                model=_model,
                messages=[{"role": "user", "content": prompt}],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            text = response.choices[0].message.content or "(empty response)"
            logger.info("Cloud text inference: %.0fms, %d chars", latency_ms, len(text))
            return text, round(latency_ms, 1)

        except Exception as exc:
            if "429" in str(exc) and attempt < MAX_RETRIES:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %.1fs...",
                    attempt + 1, MAX_RETRIES + 1, delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
