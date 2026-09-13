"""
Thin SQLite-backed telemetry store.

This is the "database" behind the simulated production environment.
Phase 2's MCP tools (query_metrics, search_logs, find_traces,
get_recent_deployments, get_kubernetes_events) will read from this
same schema, so the shape of these tables should be treated as a
mini contract between the simulator and the tool layer.

Design choice: SQLite + stdlib only, so this runs anywhere with zero
setup. Swappable for real Prometheus/ELK/etc. later without touching
the tool interfaces, as long as the tools return the same shapes.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "opsear.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    ts TEXT NOT NULL,          -- ISO 8601 UTC
    value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_lookup
    ON metrics (service, metric_name, ts);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,       -- INFO / WARN / ERROR
    message TEXT NOT NULL,
    trace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_lookup ON logs (service, ts, level);

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT NOT NULL,
    service TEXT NOT NULL,
    ts TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    status TEXT NOT NULL,      -- ok / error
    tags TEXT                  -- JSON blob, e.g. {"error_type": "db_timeout"}
);
CREATE INDEX IF NOT EXISTS idx_traces_lookup ON traces (service, ts, status);

CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    ts TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT
);
CREATE INDEX IF NOT EXISTS idx_deployments_lookup ON deployments (service, ts);

CREATE TABLE IF NOT EXISTS k8s_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    ts TEXT NOT NULL,
    pod_name TEXT,
    event_type TEXT NOT NULL,  -- Normal / Warning
    reason TEXT NOT NULL,      -- CrashLoopBackOff, Killing, OOMKilled, etc.
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_k8s_events_lookup ON k8s_events (service, ts);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(reset: bool = False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_metric(conn, service, metric_name, ts, value):
    conn.execute(
        "INSERT INTO metrics (service, metric_name, ts, value) VALUES (?, ?, ?, ?)",
        (service, metric_name, ts, value),
    )


def insert_log(conn, service, ts, level, message, trace_id=None):
    conn.execute(
        "INSERT INTO logs (service, ts, level, message, trace_id) VALUES (?, ?, ?, ?, ?)",
        (service, ts, level, message, trace_id),
    )


def insert_trace(conn, trace_id, service, ts, duration_ms, status, tags=None):
    conn.execute(
        "INSERT INTO traces (trace_id, service, ts, duration_ms, status, tags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (trace_id, service, ts, duration_ms, status, json.dumps(tags or {})),
    )


def insert_deployment(conn, service, ts, version, description=""):
    conn.execute(
        "INSERT INTO deployments (service, ts, version, description) VALUES (?, ?, ?, ?)",
        (service, ts, version, description),
    )


def insert_k8s_event(conn, service, ts, pod_name, event_type, reason, message=""):
    conn.execute(
        "INSERT INTO k8s_events (service, ts, pod_name, event_type, reason, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (service, ts, pod_name, event_type, reason, message),
    )
