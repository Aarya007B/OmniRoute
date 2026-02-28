"""
OmniRoute — Intelligent Routing Controller.

Evaluates real-time telemetry against thresholds to decide
whether a request should go to Cloud or Edge inference.

Routing Logic Matrix (priority order)
─────────────────────────────────────
1. Manual Override : force_route='cloud'/'edge' → use that
2. Offline         : no network → EDGE (only option)
3. High Latency    : ping > 150ms → EDGE (cloud too slow)
4. Low Battery     : battery < 20% AND unplugged → CLOUD (preserve battery)
5. Low RAM         : ram_available < 2GB → CLOUD (can't fit local models)
6. Cloud Optimal   : ping < 50ms → CLOUD
7. Gray Zone       : 50–150ms → CLOUD (with edge fallback on failure)
"""

from __future__ import annotations

import logging
import os

from backend.schemas import RouteTarget, RoutingDecision, TelemetrySnapshot

logger = logging.getLogger("omniroute.router")

# ── Configurable thresholds (via env vars) ───────────────────────────────────

PING_CLOUD_THRESHOLD = float(os.getenv("PING_CLOUD_THRESHOLD", "50"))
PING_EDGE_THRESHOLD = float(os.getenv("PING_EDGE_THRESHOLD", "150"))
BATTERY_LOW_THRESHOLD = float(os.getenv("BATTERY_LOW_THRESHOLD", "20"))
RAM_LOW_THRESHOLD = float(os.getenv("RAM_LOW_THRESHOLD", "2.0"))


def evaluate(telemetry: TelemetrySnapshot, force_route: str | None = None) -> RoutingDecision:
    """
    Evaluate the current telemetry and return a routing decision.

    Parameters
    ----------
    telemetry : TelemetrySnapshot
    force_route : str | None
        If 'cloud' or 'edge', bypasses telemetry evaluation.

    Returns
    -------
    RoutingDecision
        Contains the chosen target (CLOUD or EDGE), human-readable reasoning,
        and the telemetry snapshot that was used for the decision.
    """
    # ── Manual override ──────────────────────────────────────────────────
    if force_route in ("cloud", "edge"):
        target = RouteTarget.CLOUD if force_route == "cloud" else RouteTarget.EDGE
        return RoutingDecision(
            target=target,
            reasoning=f"Manual override — forced to {force_route.upper()} by user",
            telemetry=telemetry,
        )

    reasons: list[str] = []

    # ── Offline detection ────────────────────────────────────────────────
    if not telemetry.is_online or telemetry.ping_ms is None:
        reasons.append("Device is offline — no network connectivity detected")
        return RoutingDecision(
            target=RouteTarget.EDGE,
            reasoning="; ".join(reasons),
            telemetry=telemetry,
        )

    # ── High latency check ───────────────────────────────────────────────
    if telemetry.ping_ms > PING_EDGE_THRESHOLD:
        reasons.append(
            f"Network latency is high ({telemetry.ping_ms:.0f}ms > {PING_EDGE_THRESHOLD:.0f}ms threshold)"
        )
        return RoutingDecision(
            target=RouteTarget.EDGE,
            reasoning="; ".join(reasons),
            telemetry=telemetry,
        )

    # ── Critical battery check — offload to cloud to preserve battery ────
    if (
        telemetry.battery_percent is not None
        and telemetry.battery_percent < BATTERY_LOW_THRESHOLD
        and not telemetry.battery_plugged
    ):
        reasons.append(
            f"Battery critically low ({telemetry.battery_percent:.0f}% < {BATTERY_LOW_THRESHOLD:.0f}%) "
            f"and device is unplugged — offloading to cloud to preserve battery"
        )
        return RoutingDecision(
            target=RouteTarget.CLOUD,
            reasoning="; ".join(reasons),
            telemetry=telemetry,
        )

    # ── Low RAM check — edge models need memory to run ───────────────────
    if (
        telemetry.ram_available_gb is not None
        and telemetry.ram_available_gb < RAM_LOW_THRESHOLD
    ):
        reasons.append(
            f"Available RAM too low ({telemetry.ram_available_gb:.1f}GB < {RAM_LOW_THRESHOLD:.1f}GB) "
            f"— insufficient for local model inference"
        )
        return RoutingDecision(
            target=RouteTarget.CLOUD,
            reasoning="; ".join(reasons),
            telemetry=telemetry,
        )

    # ── Cloud optimal ────────────────────────────────────────────────────
    if telemetry.ping_ms < PING_CLOUD_THRESHOLD:
        reasons.append(
            f"Low latency ({telemetry.ping_ms:.0f}ms < {PING_CLOUD_THRESHOLD:.0f}ms)"
        )
        if telemetry.battery_plugged:
            reasons.append("Device is plugged in")
        elif telemetry.battery_percent is not None:
            reasons.append(f"Battery adequate ({telemetry.battery_percent:.0f}%)")
        return RoutingDecision(
            target=RouteTarget.CLOUD,
            reasoning="; ".join(reasons),
            telemetry=telemetry,
        )

    # ── Gray zone (50–150ms) — prefer cloud ──────────────────────────────
    reasons.append(
        f"Moderate latency ({telemetry.ping_ms:.0f}ms) — "
        f"cloud preferred with edge fallback if cloud fails"
    )
    return RoutingDecision(
        target=RouteTarget.CLOUD,
        reasoning="; ".join(reasons),
        telemetry=telemetry,
    )
