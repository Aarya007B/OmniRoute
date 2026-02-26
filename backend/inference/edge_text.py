"""
OmniRoute — Edge Text Inference (Apple MLX).

Uses mlx-lm to run a quantized 4-bit LLM on Apple Silicon.
Model is loaded lazily on first request.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger("omniroute.inference.edge_text")

_model = None
_tokenizer = None
_model_name: str = os.getenv(
    "MLX_MODEL", "mlx-community/Llama-3.2-1B-Instruct-4bit"
)


def _load_model():
    global _model, _tokenizer
    if _model is None:
        from mlx_lm import load

        logger.info("Loading local MLX model: %s (this may take a moment)...", _model_name)
        t0 = time.perf_counter()
        _model, _tokenizer = load(_model_name)
        logger.info(
            "MLX model loaded in %.1fs", time.perf_counter() - t0
        )
    return _model, _tokenizer


async def generate(prompt: str, max_tokens: int = 256) -> tuple[str, float]:
    """
    Run local LLM inference on Apple Silicon using MLX.
    Returns (generated_text, latency_ms).
    """
    from mlx_lm import generate as mlx_generate

    model, tokenizer = _load_model()

    # Build a chat-style prompt if the tokenizer supports it
    try:
        messages = [{"role": "user", "content": prompt}]
        formatted = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        formatted = prompt

    t0 = time.perf_counter()
    response = mlx_generate(
        model,
        tokenizer,
        prompt=formatted,
        max_tokens=max_tokens,
        verbose=False,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    logger.info("Edge text inference: %.0fms, %d chars", latency_ms, len(response))
    return response, round(latency_ms, 1)
