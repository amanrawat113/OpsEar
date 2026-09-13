# OpsEar — Phase 1

Simulated production environment + incident injection, per the build plan.

## Usage
```
cd opsear
python3 -m simulator.cli reset              # wipe DB, generate 60min baseline telemetry
python3 -m simulator.cli inject db_latency   # or bad_deployment / pod_crash_loop
python3 -m simulator.cli snapshot            # human-readable sanity check
```

Data lives in `simulator/data/opsear.db` (SQLite, git-ignored).

## Next (Phase 2)
Build the MCP server tools (`query_metrics`, `search_logs`, `find_traces`,
`get_recent_deployments`, `get_kubernetes_events`) as thin wrappers reading
from this same schema — see `simulator/telemetry/store.py` for the table
shapes each tool should query.

## Phase 2 — MCP server (verified working)

6 tools, backed by the Phase 1 SQLite store: `query_metrics`, `search_logs`,
`find_traces`, `get_recent_deployments`, `get_kubernetes_events`, `get_pod_status`.

Query logic lives in `backend/app/tools/queries.py` (pure functions, easy to
unit test). MCP wiring lives in `backend/app/mcp/server.py` (thin `@mcp.tool()`
decorators on top of the query functions).

**Tested against `mcp==2.x`** (the current stable line — note `pip install mcp`
now installs v2, a rework of v1; `FastMCP` is renamed `MCPServer`, and the
Streamable HTTP client is `mcp.client.streamable_http.streamable_http_client`,
returning a 2-tuple `(read, write)` rather than v1's 3-tuple).

### Run it
```
cd opsear
pip install -r backend/requirements.txt
python3 -m simulator.cli reset
python3 -m simulator.cli inject db_latency   # or bad_deployment / pod_crash_loop

# stdio (for MCP Inspector / local testing)
python3 -m backend.app.mcp.server

# Streamable HTTP (what Alexa+ / a remote agent connects to)
python3 -m backend.app.mcp.server --http --port 8000
# endpoint: http://127.0.0.1:8000/mcp
```

## Next (Phase 3)
Wire a Strands agent (`strands.Agent`) up to this MCP server as its tool
source, point it at Amazon Bedrock, and get the first "why is checkout
failing?" → evidence-based RCA response working end-to-end, no Alexa yet.
