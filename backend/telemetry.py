"""
OmniRoute — Real-Time Telemetry Engine.

Background daemon that continuously polls host machine state:
  • Network latency (ICMP ping to 8.8.8.8)
  • Battery state (percentage + charging)
  • Available RAM / unified memory
"""

from __future__ import annotations

import threading
import time
import logging
import subprocess

import psutil

from backend.schemas import TelemetrySnapshot

logger = logging.getLogger("omniroute.telemetry")

# ── Ping helper (subprocess-based, no root required) ────────────────────────

def _measure_ping(host: str = "8.8.8.8", timeout: int = 2) -> float | None:
    """
    Measure round-trip ping latency in milliseconds using system ping.
    Returns None if the host is unreachable or an error occurs.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout * 1000), host],
            capture_output=True,
            text=True,
            timeout=timeout + 1,
        )
        if result.returncode == 0:
            # Parse "time=XX.X ms" from output
            for part in result.stdout.split():
                if part.startswith("time="):
                    return float(part.split("=")[1])
            # macOS format: "round-trip min/avg/max/stddev = X/X/X/X ms"
            for line in result.stdout.splitlines():
                if "round-trip" in line or "rtt" in line:
                    stats = line.split("=")[1].strip().split("/")
                    return float(stats[1])  # avg
        return None
    except Exception:
        return None


# ── Telemetry Daemon ─────────────────────────────────────────────────────────

class TelemetryEngine:
    """
    Background daemon that polls system metrics every `interval` seconds
    and stores the most recent snapshot behind a thread-safe lock.
    """

    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._lock = threading.Lock()
        self._snapshot: TelemetrySnapshot = self._poll_once()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── Public API ──

    def start(self) -> None:
        """Launch the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="telemetry")
        self._thread.start()
        logger.info("Telemetry engine started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        """Signal the polling thread to stop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Telemetry engine stopped")

    def get_telemetry(self) -> TelemetrySnapshot:
        """Return the most recent telemetry snapshot (thread-safe)."""
        with self._lock:
            return self._snapshot.model_copy()

    # ── Internals ──

    def _loop(self) -> None:
        while self._running:
            try:
                snap = self._poll_once()
                with self._lock:
                    self._snapshot = snap
            except Exception as exc:
                logger.warning("Telemetry poll error: %s", exc)
            time.sleep(self._interval)

    def _poll_once(self) -> TelemetrySnapshot:
        # Network latency
        ping_ms = _measure_ping()
        is_online = ping_ms is not None

        # Battery
        battery = psutil.sensors_battery()
        if battery is not None:
            battery_percent = battery.percent
            battery_plugged = battery.power_plugged
        else:
            # Desktop Mac / no battery → treat as plugged-in at 100%
            battery_percent = 100.0
            battery_plugged = True

        # RAM
        mem = psutil.virtual_memory()
        ram_available_gb = round(mem.available / (1024 ** 3), 2)
        ram_total_gb = round(mem.total / (1024 ** 3), 2)

        return TelemetrySnapshot(
            ping_ms=round(ping_ms, 2) if ping_ms else None,
            is_online=is_online,
            battery_percent=battery_percent,
            battery_plugged=battery_plugged,
            ram_available_gb=ram_available_gb,
            ram_total_gb=ram_total_gb,
        )


# ── Module-level singleton ──────────────────────────────────────────────────

_engine: TelemetryEngine | None = None


def get_engine() -> TelemetryEngine:
    """Return (and lazily create) the global telemetry engine."""
    global _engine
    if _engine is None:
        _engine = TelemetryEngine()
    return _engine
