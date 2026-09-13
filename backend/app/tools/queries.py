"""
Pure, read-only query functions over the SQLite telemetry store built
in Phase 1 (simulator/telemetry/store.py).

Kept separate from the MCP wiring (see backend/app/mcp/server.py) on
purpose: these functions are easy to unit-test directly, and the MCP
layer becomes a thin decorator shim on top of them. If OpsEar ever
swaps SQLite for CloudWatch/ELK/Prometheus, only this file changes —
the MCP tool signatures stay the same.
"""

from datetime import datetime, timedelta, timezone

from simulator.telemetry.store import get_conn

DEFAULT_WINDOW_MINUTES = 30


def _resolve_window(start_time: str | None, end_time: str | None) -> tuple[str, str]:
    """Fill in a sensible default window (last 30 min) when the caller
    (the agent) doesn't specify explicit times."""
    now = datetime.now(timezone.utc)
    if end_time is None:
        end_time = now.isoformat(timespec="seconds")
    if start_time is None:
        start_dt = now - timedelta(minutes=DEFAULT_WINDOW_MINUTES)
        start_time = start_dt.isoformat(timespec="seconds")
    return start_time, end_time


def query_metrics(
    service: str,
    metric: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """Query a time series for one metric on one service.

    Args:
        service: Service name, e.g. "payment-service".
        metric: One of latency_ms, error_rate, cpu_pct, mem_pct,
            replica_count, db_pool_utilization_pct.
        start_time: ISO 8601 UTC start of the window. Defaults to 30
            minutes before end_time if omitted.
        end_time: ISO 8601 UTC end of the window. Defaults to now.

    Returns:
        A dict with the resolved window, the raw data points, and
        summary stats (min/max/avg/latest) so the agent doesn't have
        to compute those itself.
    """
    start_time, end_time = _resolve_window(start_time, end_time)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, value FROM metrics "
            "WHERE service = ? AND metric_name = ? AND ts BETWEEN ? AND ? "
            "ORDER BY ts ASC",
            (service, metric, start_time, end_time),
        ).fetchall()

    values = [r["value"] for r in rows]
    summary = {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "avg": (sum(values) / len(values)) if values else None,
        "latest": values[-1] if values else None,
    }
    return {
        "service": service,
        "metric": metric,
        "window": {"start": start_time, "end": end_time},
        "summary": summary,
        "points": [{"ts": r["ts"], "value": r["value"]} for r in rows],
    }


def search_logs(
    service: str,
    query: str = "",
    level: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
) -> dict:
    """Search log lines for a service in a time window.

    Args:
        service: Service name.
        query: Case-insensitive substring to match against the log
            message. Empty string matches all messages.
        level: Optional filter — "INFO", "WARN", or "ERROR".
        start_time: ISO 8601 UTC start of the window (default: 30 min ago).
        end_time: ISO 8601 UTC end of the window (default: now).
        limit: Max number of matching log lines to return, most recent first.

    Returns:
        A dict with the resolved window, a level breakdown, and the
        matching log entries.
    """
    start_time, end_time = _resolve_window(start_time, end_time)
    sql = (
        "SELECT ts, level, message, trace_id FROM logs "
        "WHERE service = ? AND ts BETWEEN ? AND ? AND message LIKE ?"
    )
    params: list = [service, start_time, end_time, f"%{query}%"]
    if level:
        sql += " AND level = ?"
        params.append(level.upper())
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        level_counts = conn.execute(
            "SELECT level, COUNT(*) c FROM logs "
            "WHERE service = ? AND ts BETWEEN ? AND ? GROUP BY level",
            (service, start_time, end_time),
        ).fetchall()

    return {
        "service": service,
        "window": {"start": start_time, "end": end_time},
        "level_counts": {r["level"]: r["c"] for r in level_counts},
        "matches": [
            {"ts": r["ts"], "level": r["level"], "message": r["message"], "trace_id": r["trace_id"]}
            for r in rows
        ],
    }


def find_traces(
    service: str,
    status: str | None = None,
    error_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
) -> dict:
    """Find distributed traces for a service in a time window.

    Args:
        service: Service name.
        status: Optional filter — "ok" or "error".
        error_type: Optional filter on the trace's tagged error_type,
            e.g. "db_timeout", "slow_query", "connection_refused".
        start_time: ISO 8601 UTC start of the window (default: 30 min ago).
        end_time: ISO 8601 UTC end of the window (default: now).
        limit: Max number of traces to return, most recent first.

    Returns:
        A dict with the resolved window, an error-rate summary
        (including the share of errors matching each error_type —
        this is what the RCA's "X% of failed traces contain Y" comes
        from), and the matching trace entries.
    """
    import json as _json

    start_time, end_time = _resolve_window(start_time, end_time)
    sql = "SELECT trace_id, ts, duration_ms, status, tags FROM traces WHERE service = ? AND ts BETWEEN ? AND ?"
    params: list = [service, start_time, end_time]
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) c FROM traces WHERE service = ? AND ts BETWEEN ? AND ?",
            (service, start_time, end_time),
        ).fetchone()["c"]
        errors = conn.execute(
            "SELECT COUNT(*) c FROM traces WHERE service = ? AND ts BETWEEN ? AND ? AND status = 'error'",
            (service, start_time, end_time),
        ).fetchone()["c"]

    traces = []
    error_type_hits = 0
    for r in rows:
        tags = _json.loads(r["tags"] or "{}")
        if error_type and tags.get("error_type") != error_type:
            continue
        if tags.get("error_type") == error_type:
            error_type_hits += 1
        traces.append({
            "trace_id": r["trace_id"], "ts": r["ts"], "duration_ms": r["duration_ms"],
            "status": r["status"], "tags": tags,
        })

    return {
        "service": service,
        "window": {"start": start_time, "end": end_time},
        "summary": {
            "total_traces": total,
            "error_traces": errors,
            "error_rate": (errors / total) if total else 0.0,
            "matching_error_type_count": error_type_hits if error_type else None,
            "matching_error_type_pct_of_errors": (
                round(100 * error_type_hits / errors, 1) if error_type and errors else None
            ),
        },
        "traces": traces,
    }


def get_recent_deployments(service: str, minutes: int = 120) -> dict:
    """List deployments for a service within the last N minutes.

    Args:
        service: Service name.
        minutes: How far back to look. Default 120 minutes — wider
            than the usual 30-minute incident window on purpose, since
            a deployment that happened slightly before the window
            still matters as a root-cause candidate.

    Returns:
        A dict with the deployments found, most recent first.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT version, ts, description FROM deployments "
            "WHERE service = ? AND ts >= ? ORDER BY ts DESC",
            (service, since),
        ).fetchall()
    return {
        "service": service,
        "since": since,
        "deployments": [
            {"version": r["version"], "ts": r["ts"], "description": r["description"]} for r in rows
        ],
    }


def get_kubernetes_events(service: str, minutes: int = 30) -> dict:
    """List Kubernetes events (pod crashes, restarts, OOMKills, etc.)
    for a service within the last N minutes.

    Args:
        service: Service name.
        minutes: How far back to look. Default 30 minutes.

    Returns:
        A dict with the events found, most recent first, plus a count
        of Warning-level events as a quick health signal.
    """
    now = datetime.now(timezone.utc)
    since = (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, pod_name, event_type, reason, message FROM k8s_events "
            "WHERE service = ? AND ts >= ? ORDER BY ts DESC",
            (service, since),
        ).fetchall()
    events = [
        {"ts": r["ts"], "pod_name": r["pod_name"], "event_type": r["event_type"],
         "reason": r["reason"], "message": r["message"]}
        for r in rows
    ]
    return {
        "service": service,
        "since": since,
        "warning_count": sum(1 for e in events if e["event_type"] == "Warning"),
        "events": events,
    }


def get_pod_status(service: str) -> dict:
    """Get the current replica/pod health snapshot for a service.

    Combines the latest replica_count metric with recent Warning-level
    k8s events, so the agent can tell "how many pods are up" and
    "what's been happening to them" in a single call.

    Args:
        service: Service name.

    Returns:
        A dict with the current replica count and any recent crash-loop
        related events.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value, ts FROM metrics WHERE service = ? AND metric_name = 'replica_count' "
            "ORDER BY ts DESC LIMIT 1",
            (service,),
        ).fetchone()

    replica_info = {"current_replicas": row["value"], "as_of": row["ts"]} if row else {
        "current_replicas": None, "as_of": None,
    }
    k8s = get_kubernetes_events(service, minutes=30)
    crash_related = [
        e for e in k8s["events"] if e["reason"] in ("CrashLoopBackOff", "OOMKilled")
    ]
    return {
        "service": service,
        **replica_info,
        "crash_related_events": crash_related,
    }
