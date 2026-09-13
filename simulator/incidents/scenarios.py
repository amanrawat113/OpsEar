"""
The three demo incidents from the OpsEar plan. Each function assumes
generate_baseline() has already been run, and *adds* an incident
signature on top of the last INCIDENT_WINDOW_MINUTES of data.

Each incident is designed so the evidence is unambiguous and
cross-checkable across at least 3 signal types (metrics, logs,
traces, deployments, or k8s events) — that's what makes the RCA
agent's evidence list meaningful instead of guesswork.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from simulator.telemetry.store import (
    get_conn,
    insert_deployment,
    insert_k8s_event,
    insert_log,
    insert_metric,
    insert_trace,
)

INCIDENT_WINDOW_MINUTES = 30
STEP_SECONDS = 30


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _ramp(fraction: float, start_val: float, end_val: float) -> float:
    """Linear ramp from start_val to end_val as fraction goes 0 -> 1."""
    return start_val + (end_val - start_val) * fraction


def inject_db_latency(now: datetime | None = None):
    """
    Incident 1: payment-db connection pool exhaustion.
    payment-service -> postgres -> pool exhaustion -> latency up -> checkout 500s up.
    Deliberately no deployment in this window, so the agent can rule that out.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=INCIDENT_WINDOW_MINUTES)

    with get_conn() as conn:
        t = start
        n_steps = max(1, int((now - start).total_seconds() // STEP_SECONDS))
        step = 0
        while t <= now:
            frac = step / n_steps

            pool_pct = _ramp(frac, 25.0, 98.0)
            payment_latency = _ramp(frac, 60.0, 60.0 * 4.2)
            checkout_error_rate = _ramp(frac, 0.004, 0.09)

            insert_metric(conn, "payment-service", "db_pool_utilization_pct", _iso(t), pool_pct)
            insert_metric(conn, "payment-service", "latency_ms", _iso(t), payment_latency)
            insert_metric(conn, "checkout-service", "error_rate", _iso(t), checkout_error_rate)

            if pool_pct > 70 and random.random() < 0.5:
                insert_log(
                    conn, "payment-service", _iso(t), "ERROR",
                    "timeout acquiring connection from pool: pool exhausted (98/100 in use)",
                )
            if checkout_error_rate > 0.03 and random.random() < 0.4:
                insert_log(
                    conn, "checkout-service", _iso(t), "ERROR",
                    "checkout failed: payment-service returned 500 (upstream timeout)",
                )

            # Traces: increasing share tagged db_timeout as the window progresses.
            for _ in range(random.randint(1, 4)):
                trace_id = str(uuid.uuid4())
                is_timeout = random.random() < frac * 0.73 + 0.05
                insert_trace(
                    conn, trace_id, "payment-service", _iso(t),
                    duration_ms=payment_latency if is_timeout else 55.0,
                    status="error" if is_timeout else "ok",
                    tags={"error_type": "db_timeout"} if is_timeout else {},
                )
            t += timedelta(seconds=STEP_SECONDS)
            step += 1

    return {
        "name": "db_latency",
        "expected_root_cause": "Database connection pool exhaustion on payment-db",
        "primary_service": "payment-service",
        "window_start": _iso(start),
        "window_end": _iso(now),
    }


def inject_bad_deployment(now: datetime | None = None):
    """
    Incident 2: deployment v2.8 introduces a slow query.
    Deployment lands 4 minutes into the window; latency/errors climb only after it.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=INCIDENT_WINDOW_MINUTES)
    deploy_time = start + timedelta(minutes=4)

    with get_conn() as conn:
        insert_deployment(
            conn, "payment-service", _iso(deploy_time), "v2.8",
            "Add order-history lookup to payment confirmation path",
        )

        t = start
        n_steps = max(1, int((now - start).total_seconds() // STEP_SECONDS))
        step = 0
        while t <= now:
            frac = step / n_steps
            post_deploy = t >= deploy_time
            post_frac = 0.0
            if post_deploy:
                post_frac = (t - deploy_time).total_seconds() / max(
                    1, (now - deploy_time).total_seconds()
                )

            payment_latency = 60.0 if not post_deploy else _ramp(post_frac, 60.0, 60.0 * 3.5)
            checkout_error_rate = 0.004 if not post_deploy else _ramp(post_frac, 0.004, 0.07)

            insert_metric(conn, "payment-service", "latency_ms", _iso(t), payment_latency)
            insert_metric(conn, "checkout-service", "error_rate", _iso(t), checkout_error_rate)

            if post_deploy and random.random() < 0.4:
                insert_log(
                    conn, "payment-service", _iso(t), "WARN",
                    "slow query detected: order_history lookup took 2100ms (query added in v2.8)",
                )

            for _ in range(random.randint(1, 3)):
                trace_id = str(uuid.uuid4())
                is_slow = post_deploy and random.random() < post_frac * 0.6 + 0.1
                insert_trace(
                    conn, trace_id, "payment-service", _iso(t),
                    duration_ms=payment_latency if is_slow else 58.0,
                    status="error" if is_slow and random.random() < 0.3 else "ok",
                    tags={"error_type": "slow_query", "deployment": "v2.8"} if is_slow else {},
                )
            t += timedelta(seconds=STEP_SECONDS)
            step += 1

    return {
        "name": "bad_deployment",
        "expected_root_cause": "Deployment v2.8 introduced a slow query on the payment confirmation path",
        "primary_service": "payment-service",
        "deployment_time": _iso(deploy_time),
        "window_start": _iso(start),
        "window_end": _iso(now),
    }


def inject_pod_crash_loop(now: datetime | None = None):
    """
    Incident 3: checkout-service pods enter CrashLoopBackOff.
    Replica count drops, remaining pods get overloaded, 5xx rate climbs.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(minutes=INCIDENT_WINDOW_MINUTES)
    pods = [f"checkout-service-{i}" for i in range(4)]

    with get_conn() as conn:
        t = start
        n_steps = max(1, int((now - start).total_seconds() // STEP_SECONDS))
        step = 0
        crashed_pods = set()
        while t <= now:
            frac = step / n_steps

            # Pods start crashing partway through the window.
            if frac > 0.15 and len(crashed_pods) < 3 and random.random() < 0.12:
                pod = random.choice([p for p in pods if p not in crashed_pods])
                crashed_pods.add(pod)
                insert_k8s_event(
                    conn, "checkout-service", _iso(t), pod, "Warning", "OOMKilled",
                    "Container checkout-service exceeded memory limit (512Mi)",
                )
                insert_k8s_event(
                    conn, "checkout-service", _iso(t), pod, "Warning", "CrashLoopBackOff",
                    f"Back-off restarting failed container in pod {pod}",
                )
                insert_log(
                    conn, "checkout-service", _iso(t), "ERROR",
                    f"pod {pod} terminated: OOMKilled, restart count increasing",
                )

            replicas = max(1, len(pods) - len(crashed_pods))
            insert_metric(conn, "checkout-service", "replica_count", _iso(t), replicas)

            overload_factor = 1 + (len(pods) - replicas) * 0.9
            latency = 120.0 * overload_factor
            error_rate = min(0.4, 0.004 * overload_factor**2)

            insert_metric(conn, "checkout-service", "latency_ms", _iso(t), latency)
            insert_metric(conn, "checkout-service", "error_rate", _iso(t), error_rate)

            for _ in range(random.randint(1, 4)):
                trace_id = str(uuid.uuid4())
                is_error = random.random() < error_rate
                insert_trace(
                    conn, trace_id, "checkout-service", _iso(t),
                    duration_ms=latency,
                    status="error" if is_error else "ok",
                    tags={"error_type": "connection_refused"} if is_error else {},
                )
            t += timedelta(seconds=STEP_SECONDS)
            step += 1

    return {
        "name": "pod_crash_loop",
        "expected_root_cause": "checkout-service pods OOMKilled and stuck in CrashLoopBackOff, "
                                "reducing replica count and overloading remaining pods",
        "primary_service": "checkout-service",
        "window_start": _iso(start),
        "window_end": _iso(now),
    }


SCENARIOS = {
    "db_latency": inject_db_latency,
    "bad_deployment": inject_bad_deployment,
    "pod_crash_loop": inject_pod_crash_loop,
}
