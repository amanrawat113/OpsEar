"""
OpsEar MCP Server.

Wires the read-only query functions in backend/app/tools/queries.py
up as MCP tools, using the MCP Python SDK v2 (`mcp.server.MCPServer`,
confirmed API — see backend/README.md for the version notes).

Run locally (stdio, for quick testing with the MCP Inspector or a
local client):
    python -m backend.app.mcp.server

Run as a Streamable HTTP server (what Alexa+ / a remote agent will
actually connect to):
    python -m backend.app.mcp.server --http --port 8000

Then the MCP endpoint is http://<host>:8000/mcp
"""

import argparse

from mcp.server import MCPServer

from backend.app.tools import queries

mcp = MCPServer(
    name="opsear",
    title="OpsEar",
    description=(
        "Tools for investigating production incidents: query service "
        "metrics, search logs, find distributed traces, and check "
        "recent deployments and Kubernetes events."
    ),
)


@mcp.tool()
def query_metrics(
    service: str,
    metric: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """Query a time series for one metric on one service.

    metric must be one of: latency_ms, error_rate, cpu_pct, mem_pct,
    replica_count, db_pool_utilization_pct.
    Times are ISO 8601 UTC; if omitted, defaults to the last 30 minutes.
    """
    return queries.query_metrics(service, metric, start_time, end_time)


@mcp.tool()
def search_logs(
    service: str,
    query: str = "",
    level: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
) -> dict:
    """Search log lines for a service. `level` filters to INFO/WARN/ERROR.
    Times are ISO 8601 UTC; if omitted, defaults to the last 30 minutes.
    """
    return queries.search_logs(service, query, level, start_time, end_time, limit)


@mcp.tool()
def find_traces(
    service: str,
    status: str | None = None,
    error_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
) -> dict:
    """Find distributed traces for a service. `status` is "ok" or "error".
    `error_type` filters to a tagged failure category, e.g. "db_timeout",
    "slow_query", "connection_refused". Returns a summary including what
    share of errors match error_type — useful for evidence like
    "73% of failed traces contain a DB timeout".
    """
    return queries.find_traces(service, status, error_type, start_time, end_time, limit)


@mcp.tool()
def get_recent_deployments(service: str, minutes: int = 120) -> dict:
    """List deployments for a service within the last N minutes (default 120)."""
    return queries.get_recent_deployments(service, minutes)


@mcp.tool()
def get_kubernetes_events(service: str, minutes: int = 30) -> dict:
    """List Kubernetes events (crashes, restarts, OOMKills) for a service
    within the last N minutes (default 30)."""
    return queries.get_kubernetes_events(service, minutes)


@mcp.tool()
def get_pod_status(service: str) -> dict:
    """Get current replica count and any recent crash-loop related
    Kubernetes events for a service."""
    return queries.get_pod_status(service)


def main():
    parser = argparse.ArgumentParser(description="Run the OpsEar MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
