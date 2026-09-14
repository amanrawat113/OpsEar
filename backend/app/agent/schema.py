"""
The RCA output contract. Passed to Agent(structured_output_model=...)
so the model's final answer is coerced into exactly this shape instead
of free-form prose.
"""

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    description: str = Field(
        description="One concrete, checkable fact, e.g. "
                     "'Database latency increased 4.2x' or "
                     "'73% of failed traces contain a DB timeout'."
    )
    source_tool: str = Field(
        description="Which tool call produced this evidence, e.g. 'query_metrics' or 'find_traces'."
    )


class RootCauseAnalysis(BaseModel):
    service: str = Field(description="The primary service identified as the source of the incident.")
    root_cause: str = Field(description="A one-sentence statement of the root cause.")
    confidence_pct: int = Field(
        ge=0, le=100,
        description="Confidence in this root cause, 0-100, based on how much of the "
                     "gathered evidence points the same direction.",
    )
    evidence: list[EvidenceItem] = Field(
        description="3-6 concrete, tool-sourced facts supporting the root cause. "
                     "Never fewer than 2 — if you can't find that much evidence, "
                     "confidence should be low and that should be reflected."
    )
    ruled_out: list[str] = Field(
        default_factory=list,
        description="Other causes actively checked and ruled out, e.g. "
                     "'No recent deployment in the incident window' or "
                     "'CPU and memory remained normal'.",
    )
    recommended_action: str = Field(description="A concrete, actionable next step.")