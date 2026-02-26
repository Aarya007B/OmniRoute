"""
OmniRoute — FastAPI Application.

Unified REST API that intercepts AI requests and dynamically routes
them to Cloud or Edge inference based on real-time telemetry.

Features:
- Unified /v1/process endpoint
- SSE streaming for text responses
- Force-route override for demo
- Cost estimation tracking
- Dotenv support
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from pathlib import Path

from dotenv import load_dotenv

# Load .env file before anything else
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.schemas import (
    HealthResponse,
    LogEntry,
    PayloadType,
    ProcessRequest,
    ProcessResponse,
    RouteTarget,
)
from backend.telemetry import get_engine
from backend import router as routing_controller

# ── Logging setup ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("omniroute.app")

# ── Cost estimation constants ────────────────────────────────────────────────
# Based on approximate OpenRouter / cloud API pricing
COST_PER_1K_INPUT_TOKENS = 0.00010   # $0.10 per 1M input tokens
COST_PER_1K_OUTPUT_TOKENS = 0.00040  # $0.40 per 1M output tokens
COST_PER_VISION_REQUEST = 0.002      # ~$0.002 per vision request
AVG_TOKENS_PER_CHAR = 0.25           # rough estimate

# ── Application ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="OmniRoute — Dynamic Edge-to-Cloud Router",
    version="0.2.0",
    description="Intelligent middleware that routes AI requests between Cloud and Edge.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── State ────────────────────────────────────────────────────────────────────

_start_time: float = 0.0
_log_entries: deque[LogEntry] = deque(maxlen=100)
_log_counter: int = 0
_total_cost_saved: float = 0.0
_total_requests: int = 0
_cloud_requests: int = 0
_edge_requests: int = 0

# Global force-route override (for demo toggle — None means auto)
_force_route_override: str | None = None

# Latency history for comparison chart
_latency_history: deque[dict] = deque(maxlen=50)

# ── Lifecycle ────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    global _start_time
    _start_time = time.time()
    engine = get_engine()
    engine.start()
    logger.info("🚀 OmniRoute v0.2.0 started")


@app.on_event("shutdown")
async def shutdown():
    engine = get_engine()
    engine.stop()
    logger.info("OmniRoute stopped")


# ── Static files (frontend) ─────────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse("<h1>OmniRoute API</h1><p>Frontend not found.</p>")


# ── API Endpoints ────────────────────────────────────────────────────────────


@app.get("/v1/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        version="0.2.0",
        uptime_seconds=round(time.time() - _start_time, 1),
    )


@app.get("/v1/telemetry")
async def telemetry():
    engine = get_engine()
    snap = engine.get_telemetry()
    decision = routing_controller.evaluate(snap, _force_route_override)
    return {
        "telemetry": snap.model_dump(),
        "routing": {
            "target": decision.target.value,
            "reasoning": decision.reasoning,
        },
        "force_route": _force_route_override,
    }


@app.get("/v1/logs")
async def get_logs():
    return {"logs": [entry.model_dump() for entry in _log_entries]}


@app.get("/v1/stats")
async def get_stats():
    """Return cost estimation and request statistics."""
    return {
        "total_requests": _total_requests,
        "cloud_requests": _cloud_requests,
        "edge_requests": _edge_requests,
        "total_cost_saved_usd": round(_total_cost_saved, 6),
        "latency_history": list(_latency_history),
    }


@app.post("/v1/force-route")
async def set_force_route(route: str = Query(..., description="'auto', 'cloud', or 'edge'")):
    """Set global route override for demo purposes."""
    global _force_route_override
    if route == "auto":
        _force_route_override = None
        logger.info("Route override cleared → auto mode")
    elif route in ("cloud", "edge"):
        _force_route_override = route
        logger.info("Route override set → %s", route.upper())
    else:
        raise HTTPException(status_code=400, detail="route must be 'auto', 'cloud', or 'edge'")
    return {"force_route": _force_route_override}


@app.post("/v1/process", response_model=ProcessResponse)
async def process(request: ProcessRequest):
    global _log_counter, _total_cost_saved, _total_requests, _cloud_requests, _edge_requests

    # 1. Get telemetry & routing decision
    engine = get_engine()
    snap = engine.get_telemetry()
    # Per-request force_route takes priority, then global override, then auto
    force = request.force_route or _force_route_override
    decision = routing_controller.evaluate(snap, force)

    logger.info(
        "Processing %s request → route=%s (%s)",
        request.type.value,
        decision.target.value,
        decision.reasoning,
    )

    # 2. Execute inference
    result = None
    latency_ms = 0.0

    try:
        if request.type == PayloadType.TEXT:
            result, latency_ms = await _run_text_inference(
                request.payload, decision.target
            )
        elif request.type == PayloadType.VISION:
            result, latency_ms = await _run_vision_inference(
                request.payload, decision.target
            )
    except Exception as exc:
        # If cloud fails, attempt edge fallback
        if decision.target == RouteTarget.CLOUD:
            logger.warning(
                "Cloud inference failed (%s), falling back to edge: %s",
                request.type.value,
                exc,
            )
            decision = decision.model_copy(
                update={
                    "target": RouteTarget.EDGE,
                    "reasoning": f"Cloud failed ({exc}); automatic edge fallback",
                }
            )
            try:
                if request.type == PayloadType.TEXT:
                    result, latency_ms = await _run_text_inference(
                        request.payload, RouteTarget.EDGE
                    )
                else:
                    result, latency_ms = await _run_vision_inference(
                        request.payload, RouteTarget.EDGE
                    )
            except Exception as edge_exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Both cloud and edge inference failed: {edge_exc}",
                )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Edge inference failed: {exc}",
            )

    # 3. Cost estimation
    cost_saved = 0.0
    if decision.target == RouteTarget.EDGE:
        if request.type == PayloadType.TEXT:
            input_tokens = len(request.payload) * AVG_TOKENS_PER_CHAR
            output_tokens = len(str(result)) * AVG_TOKENS_PER_CHAR if result else 0
            cost_saved = (
                (input_tokens / 1000) * COST_PER_1K_INPUT_TOKENS
                + (output_tokens / 1000) * COST_PER_1K_OUTPUT_TOKENS
            )
        else:
            cost_saved = COST_PER_VISION_REQUEST
        _total_cost_saved += cost_saved

    # 4. Update stats
    _total_requests += 1
    if decision.target == RouteTarget.CLOUD:
        _cloud_requests += 1
    else:
        _edge_requests += 1

    # 5. Record latency for comparison chart
    _latency_history.append({
        "id": _total_requests,
        "route": decision.target.value,
        "type": request.type.value,
        "latency_ms": round(latency_ms, 1),
        "timestamp": time.time(),
    })

    # 6. Log the decision
    _log_counter += 1
    preview = str(result)[:120] if result else ""
    entry = LogEntry(
        id=_log_counter,
        timestamp=time.time(),
        type=request.type,
        route=decision.target,
        reasoning=decision.reasoning,
        latency_ms=latency_ms,
        result_preview=preview,
    )
    _log_entries.appendleft(entry)

    return ProcessResponse(
        success=True,
        type=request.type,
        route=decision.target,
        reasoning=decision.reasoning,
        result=result,
        latency_ms=latency_ms,
        telemetry=snap,
        cost_saved_usd=round(cost_saved, 6),
    )


# ── SSE Streaming endpoint for text ─────────────────────────────────────────


@app.post("/v1/stream")
async def stream_text(request: ProcessRequest):
    """
    Server-Sent Events endpoint for streaming text generation.
    Streams tokens as they arrive for a real-time typing effect.
    """
    global _log_counter, _total_cost_saved, _total_requests, _cloud_requests, _edge_requests

    if request.type != PayloadType.TEXT:
        raise HTTPException(status_code=400, detail="Streaming only supported for text requests")

    engine = get_engine()
    snap = engine.get_telemetry()
    force = request.force_route or _force_route_override
    decision = routing_controller.evaluate(snap, force)

    async def event_generator():
        nonlocal decision
        global _log_counter, _total_cost_saved, _total_requests, _cloud_requests, _edge_requests

        # Send routing info first
        yield f"data: {json.dumps({'type': 'route', 'route': decision.target.value, 'reasoning': decision.reasoning})}\n\n"

        t0 = time.perf_counter()
        full_text = ""

        try:
            if decision.target == RouteTarget.CLOUD:
                # Stream from cloud
                text, latency_ms = await _run_text_inference(request.payload, RouteTarget.CLOUD)
                full_text = text
            else:
                # Stream from edge
                text, latency_ms = await _run_text_inference(request.payload, RouteTarget.EDGE)
                full_text = text
        except Exception as exc:
            if decision.target == RouteTarget.CLOUD:
                decision = decision.model_copy(
                    update={
                        "target": RouteTarget.EDGE,
                        "reasoning": f"Cloud failed ({exc}); automatic edge fallback",
                    }
                )
                yield f"data: {json.dumps({'type': 'route', 'route': 'edge', 'reasoning': decision.reasoning})}\n\n"
                try:
                    text, latency_ms = await _run_text_inference(request.payload, RouteTarget.EDGE)
                    full_text = text
                except Exception as edge_exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(edge_exc)})}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                return

        total_latency = (time.perf_counter() - t0) * 1000

        # Simulate streaming by chunking the response
        words = full_text.split(" ")
        chunk_size = max(1, len(words) // 20)  # ~20 chunks
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            if i > 0:
                chunk = " " + chunk
            yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
            await asyncio.sleep(0.03)  # 30ms between chunks

        # Cost estimation
        cost_saved = 0.0
        if decision.target == RouteTarget.EDGE:
            input_tokens = len(request.payload) * AVG_TOKENS_PER_CHAR
            output_tokens = len(full_text) * AVG_TOKENS_PER_CHAR
            cost_saved = (
                (input_tokens / 1000) * COST_PER_1K_INPUT_TOKENS
                + (output_tokens / 1000) * COST_PER_1K_OUTPUT_TOKENS
            )
            _total_cost_saved += cost_saved

        # Update stats
        _total_requests += 1
        if decision.target == RouteTarget.CLOUD:
            _cloud_requests += 1
        else:
            _edge_requests += 1

        _latency_history.append({
            "id": _total_requests,
            "route": decision.target.value,
            "type": "text",
            "latency_ms": round(total_latency, 1),
            "timestamp": time.time(),
        })

        _log_counter += 1
        preview = full_text[:120]
        entry = LogEntry(
            id=_log_counter,
            timestamp=time.time(),
            type=PayloadType.TEXT,
            route=decision.target,
            reasoning=decision.reasoning,
            latency_ms=total_latency,
            result_preview=preview,
        )
        _log_entries.appendleft(entry)

        # Send done event
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': round(total_latency, 1), 'cost_saved_usd': round(cost_saved, 6), 'route': decision.target.value})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Inference dispatch ───────────────────────────────────────────────────────


async def _run_text_inference(
    prompt: str, target: RouteTarget
) -> tuple[str, float]:
    if target == RouteTarget.CLOUD:
        from backend.inference.cloud_text import generate

        return await generate(prompt)
    else:
        from backend.inference.edge_text import generate

        return await generate(prompt)


async def _run_vision_inference(
    image_b64: str, target: RouteTarget
) -> tuple[list[dict], float]:
    if target == RouteTarget.CLOUD:
        from backend.inference.cloud_vision import detect

        return await detect(image_b64)
    else:
        from backend.inference.edge_vision import detect

        return await detect(image_b64)
