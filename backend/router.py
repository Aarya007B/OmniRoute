"""
OmniRoute — Intelligent Routing Controller.

Evaluates real-time telemetry against thresholds to decide
whether a request should go to Cloud or Edge inference.

Routing Logic Matrix
────────────────────
Cloud Optimal : ping < 50ms AND (battery > 20% OR plugged in)
Edge Fallback : ping > 150ms OR offline OR (battery < 20% AND unplugged)
Gray Zone     : 50–150ms → prefer cloud, fallback to edge on failure
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

    # ── Critical battery check ───────────────────────────────────────────
    if (
        telemetry.battery_percent is not None
        and telemetry.battery_percent < BATTERY_LOW_THRESHOLD
        and not telemetry.battery_plugged
    ):
        reasons.append(
            f"Battery critically low ({telemetry.battery_percent:.0f}% < {BATTERY_LOW_THRESHOLD:.0f}%) "
            f"and device is unplugged"
        )
        return RoutingDecision(
            target=RouteTarget.EDGE,
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
