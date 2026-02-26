"""
OmniRoute — Cloud Vision Inference (Groq API).

Sends base64-encoded image to Groq's vision model for object detection.
Uses Groq's OpenAI-compatible endpoint.
Includes exponential backoff retry for rate limits.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import time

from openai import OpenAI
from PIL import Image

logger = logging.getLogger("omniroute.inference.cloud_vision")

_client: OpenAI | None = None
_vision_model: str = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# Retry config for rate limits
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds

DETECTION_PROMPT = (
    "Analyze this image and identify all objects you can see. "
    "For each object, provide:\n"
    "1. The object label/name\n"
    "2. Your confidence level (0.0 to 1.0)\n"
    "3. Approximate bounding box as [x1, y1, x2, y2] normalized to 0-1 range\n\n"
    "Return your response as a JSON array of objects with keys: "
    '"label", "confidence", "bbox". '
    "Only return the JSON array, no other text."
)


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
        logger.info("Groq vision client initialized (model=%s)", _vision_model)
    return _client


def _prepare_image_url(b64_data: str) -> str:
    """Ensure base64 data has a proper data URI prefix for the API."""
    if b64_data.startswith("data:"):
        return b64_data
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    # Detect MIME type from header bytes
    raw = base64.b64decode(b64_data[:32] + "==")
    if raw[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif raw[:4] == b"\x89PNG":
        mime = "image/png"
    elif raw[:4] == b"GIF8":
        mime = "image/gif"
    elif raw[:4] == b"RIFF":
        mime = "image/webp"
    else:
        mime = "image/png"
    return f"data:{mime};base64,{b64_data}"


async def detect(image_b64: str) -> tuple[list[dict], float]:
    """
    Send an image to Groq for object detection.
    Returns (list_of_detections, latency_ms).
    Each detection: {"label": str, "confidence": float, "bbox": [x1,y1,x2,y2]}
    Retries with exponential backoff on rate-limit (429) errors.
    """
    client = _get_client()
    image_url = _prepare_image_url(image_b64)

    for attempt in range(MAX_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            response = client.chat.completions.create(
                model=_vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": DETECTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    }
                ],
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            # Parse JSON from response
            text = response.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            try:
                detections = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Failed to parse Groq vision response as JSON: %s", text[:200])
                detections = [{"label": "unknown", "confidence": 0.5, "bbox": [0.1, 0.1, 0.9, 0.9]}]

            logger.info("Cloud vision inference: %.0fms, %d objects", latency_ms, len(detections))
            return detections, round(latency_ms, 1)

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
