"""
Generates baseline ("everything is fine") telemetry for the last
WINDOW_MINUTES minutes, at STEP_SECONDS resolution, for every service
in the topology.

Run this first, before injecting an incident, so there's a normal
signal for the agent to compare against.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from simulator.services.topology import SERVICES
from simulator.telemetry.store import (
    get_conn,
    init_db,
    insert_deployment,
    insert_log,
    insert_metric,
    insert_trace,
)

WINDOW_MINUTES = 60
STEP_SECONDS = 30
NOISE = 0.08  # +/- 8% jitter on baseline values


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _jitter(value: float, noise: float = NOISE) -> float:
    return max(0.0, value * (1 + random.uniform(-noise, noise)))


def generate_baseline(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=WINDOW_MINUTES)

    init_db(reset=True)

    with get_conn() as conn:
        # A few uneventful deployments, well outside the incident window,
        # so "recent deployments" queries have realistic history to sift through.
        insert_deployment(
            conn, "checkout-service",
            _iso(start - timedelta(hours=6)), "v4.11", "Minor UI copy fix",
        )
        insert_deployment(
            conn, "payment-service",
            _iso(start - timedelta(hours=18)), "v2.7", "Add retry logic for gateway calls",
        )
        insert_deployment(
            conn, "inventory-service",
            _iso(start - timedelta(days=2)), "v1.9", "Bump dependency versions",
        )

        t = start
        while t <= now:
            for name, svc in SERVICES.items():
                if name.endswith("-db"):
                    continue  # datastores don't emit app-level HTTP metrics

                latency = _jitter(svc.baseline_latency_ms)
                error_rate = _jitter(svc.baseline_error_rate, noise=0.3)
                cpu = _jitter(svc.baseline_cpu_pct)
                mem = _jitter(svc.baseline_mem_pct)
                pool = _jitter(svc.baseline_pool_utilization_pct)

                insert_metric(conn, name, "latency_ms", _iso(t), latency)
                insert_metric(conn, name, "error_rate", _iso(t), error_rate)
                insert_metric(conn, name, "cpu_pct", _iso(t), cpu)
                insert_metric(conn, name, "mem_pct", _iso(t), mem)
                insert_metric(conn, name, "replica_count", _iso(t), svc.baseline_replicas)
                if svc.depends_on and any(d.endswith("-db") for d in svc.depends_on):
                    insert_metric(conn, name, "db_pool_utilization_pct", _iso(t), pool)

                # Sparse baseline logs — mostly quiet, occasional INFO.
                if random.random() < 0.15:
                    insert_log(conn, name, _iso(t), "INFO", f"{name} handled request batch normally")
                if random.random() < 0.02:
                    insert_log(conn, name, _iso(t), "WARN", f"{name} saw a slow-ish response (non-critical)")

                # A handful of traces per step, almost all successful.
                for _ in range(random.randint(1, 3)):
                    trace_id = str(uuid.uuid4())
                    is_error = random.random() < svc.baseline_error_rate
                    insert_trace(
                        conn, trace_id, name, _iso(t),
                        duration_ms=_jitter(svc.baseline_latency_ms),
                        status="error" if is_error else "ok",
                        tags={"error_type": "transient"} if is_error else {},
                    )
            t += timedelta(seconds=STEP_SECONDS)

    return start, now


if __name__ == "__main__":
    start, end = generate_baseline()
    print(f"Baseline telemetry generated from {start.isoformat()} to {end.isoformat()}")
