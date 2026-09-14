"""
The OpsEar investigation agent.

Connects to the Phase 2 MCP server as its tool source, reasons over
which tools to call, and returns a structured RootCauseAnalysis.

Requires AWS credentials with Bedrock model access enabled. Configure
via env vars, ~/.aws/credentials, or an instance role once deployed.

Usage:
    python -m backend.app.agent.rca_agent "why is checkout failing?"

Make sure the MCP server is already running first:
    python -m backend.app.mcp.server --http --port 8000
"""

import argparse
import os

from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from backend.app.agent.schema import RootCauseAnalysis

SYSTEM_PROMPT = """\
You are OpsEar, a production incident investigation agent. You have \
tools to query metrics, search logs, find distributed traces, and \
check recent deployments and Kubernetes events for any service.

When asked to investigate an incident:
1. Start broad: check metrics and traces for the service the user \
mentioned to see what's abnormal.
2. Follow the evidence: if you see high latency or errors, check \
whether a recent deployment or a dependency (e.g. a database, or an \
upstream/downstream service) explains it. Check Kubernetes events if \
pod health could be involved.
3. Actively try to rule out alternative explanations, not just \
confirm the first hypothesis. Note what you checked and ruled out.
4. Only conclude once you have at least 2-3 independent pieces of \
supporting evidence from different tools (not just one metric).
5. Be honest about confidence: if the evidence is thin or conflicting, \
say so with a lower confidence score rather than overstating certainty.

Do not guess at service names — if the user doesn't name one, start \
with "checkout-service" since it's the customer-facing entry point, \
and follow its dependencies (payment-service, inventory-service) if \
its own metrics look normal but something's still wrong.
"""


def build_agent(mcp_url: str = "http://127.0.0.1:8000/mcp", region: str | None = None) -> tuple[Agent, MCPClient]:
    """Build the agent and its MCP client. Caller is responsible for
    using the MCP client as a context manager while calling the agent,
    e.g.:

        agent, mcp_client = build_agent()
        with mcp_client:
            result = agent("why is checkout failing?")
    """
    mcp_client = MCPClient(url=mcp_url)
    with mcp_client:
        tools = mcp_client.list_tools_sync()

    model = BedrockModel(
        # IMPORTANT: set this to the exact inference profile ID for your
        # region and account — check the AWS Bedrock console under
        # "Model access" / "Cross-region inference" for the current ID.
        # Current Claude models on Bedrock require an inference profile
        # (e.g. "us.anthropic.claude-sonnet-4-6"), not a bare model ID.
        model_id=os.environ["OPSEAR_BEDROCK_MODEL_ID"],
        region_name=region or os.environ.get("AWS_REGION", "us-east-1"),
    )

    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        structured_output_model=RootCauseAnalysis,
    )
    return agent, mcp_client


def compute_confidence(evidence: list) -> int:
    """Deterministic confidence score based on independent supporting
    signals — not the model's own self-assessment. More evidence items
    and more distinct tool sources both increase confidence, capped
    below 100 since nothing is ever fully certain from telemetry alone.
    """
    if not evidence:
        return 0
    distinct_sources = {e.source_tool for e in evidence}
    score = min(len(evidence) * 0.12, 0.50)
    score += min(len(distinct_sources) * 0.15, 0.45)
    return round(min(score, 0.97) * 100)


def investigate(question: str, mcp_url: str = "http://127.0.0.1:8000/mcp") -> RootCauseAnalysis:
    """Run one investigation end-to-end and return the structured RCA."""
    agent, mcp_client = build_agent(mcp_url=mcp_url)
    with mcp_client:
        result = agent(question)
    rca = result.structured_output
    rca.confidence_pct = compute_confidence(rca.evidence)
    return rca

def run_interactive_session(mcp_url: str = "http://127.0.0.1:8000/mcp"):
    """Interactive terminal session. The same agent instance handles every
    question, so follow-ups like 'why?' or 'what should I do?' have full
    context from earlier turns — this is the conversational behavior the
    Alexa+ integration will eventually rely on. Type 'exit' to quit.
    """
    agent, mcp_client = build_agent(mcp_url=mcp_url)
    with mcp_client:
        print("OpsEar investigation session. Type 'exit' to quit.\n")
        while True:
            question = input("> ").strip()
            if question.lower() in ("exit", "quit"):
                break
            result = agent(question)
            if result.structured_output:
                rca = result.structured_output
                rca.confidence_pct = compute_confidence(rca.evidence)
                print(rca.model_dump_json(indent=2))
            else:
                print(result.message)
            print()


def main():
    parser = argparse.ArgumentParser(description="Run an OpsEar investigation")
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--interactive", action="store_true", help="Start a follow-up-capable session")
    args = parser.parse_args()

    if args.interactive:
        run_interactive_session(mcp_url=args.mcp_url)
    else:
        rca = investigate(args.question or "Why is checkout failing?", mcp_url=args.mcp_url)
        print(rca.model_dump_json(indent=2))


if __name__ == "__main__":
    main()