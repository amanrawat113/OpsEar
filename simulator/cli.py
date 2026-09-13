"""
Usage:
    python -m simulator.cli reset
    python -m simulator.cli inject db_latency
    python -m simulator.cli inject bad_deployment
    python -m simulator.cli inject pod_crash_loop
    python -m simulator.cli snapshot
"""

import sys

from simulator.incidents.scenarios import SCENARIOS
from simulator.telemetry.generator import generate_baseline
from simulator.telemetry.store import get_conn


def cmd_reset():
    start, end = generate_baseline()
    print(f"Reset + baseline generated: {start.isoformat()} -> {end.isoformat()}")


def cmd_inject(name: str):
    if name not in SCENARIOS:
        print(f"Unknown scenario '{name}'. Options: {list(SCENARIOS)}")
        sys.exit(1)
    result = SCENARIOS[name]()
    print(f"Injected incident: {result['name']}")
    print(f"  Expected root cause: {result['expected_root_cause']}")
    print(f"  Primary service:     {result['primary_service']}")
    print(f"  Window:              {result['window_start']} -> {result['window_end']}")


def cmd_snapshot():
    """Quick human-readable summary per service, for sanity-checking the data
    before Phase 2 tools are built on top of it."""
    with get_conn() as conn:
        services = [r["service"] for r in conn.execute(
            "SELECT DISTINCT service FROM metrics ORDER BY service"
        )]
        for svc in services:
            print(f"\n== {svc} ==")
            for metric in ["latency_ms", "error_rate", "db_pool_utilization_pct", "replica_count"]:
                row = conn.execute(
                    "SELECT value FROM metrics WHERE service=? AND metric_name=? "
                    "ORDER BY ts DESC LIMIT 1",
                    (svc, metric),
                ).fetchone()
                if row:
                    print(f"  latest {metric}: {row['value']:.2f}")

            err_traces = conn.execute(
                "SELECT COUNT(*) c FROM traces WHERE service=? AND status='error'", (svc,)
            ).fetchone()["c"]
            total_traces = conn.execute(
                "SELECT COUNT(*) c FROM traces WHERE service=?", (svc,)
            ).fetchone()["c"]
            print(f"  traces: {err_traces}/{total_traces} error")

            deploys = conn.execute(
                "SELECT version, ts FROM deployments WHERE service=? ORDER BY ts DESC LIMIT 1",
                (svc,),
            ).fetchone()
            if deploys:
                print(f"  last deployment: {deploys['version']} at {deploys['ts']}")

            k8s = conn.execute(
                "SELECT COUNT(*) c FROM k8s_events WHERE service=? AND event_type='Warning'",
                (svc,),
            ).fetchone()["c"]
            if k8s:
                print(f"  warning k8s events: {k8s}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "reset":
        cmd_reset()
    elif cmd == "inject":
        cmd_inject(sys.argv[2])
    elif cmd == "snapshot":
        cmd_snapshot()
    else:
        print(__doc__)
        sys.exit(1)
