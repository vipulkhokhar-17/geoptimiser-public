"""The typed graph state and the agent's outward-facing result contract."""

from typing import Any, Literal, TypedDict

from geoptimiser.recommendations import RecommendationSet
from geoptimiser.schemas import (
    EvidenceRef,
    Identifier,
    SchemaModel,
    UtcDatetime,
    VersionedRecord,
)

Status = Literal["running", "completed", "incomplete", "failed"]
StepStatus = Literal["ok", "error", "rejected", "invalid", "timeout"]


class AgentState(TypedDict):
    """What flows between graph nodes: plain, serialisable data only.

    Live objects (the audit run, retriever, model) stay in the runtime, not here, so
    state can be checkpointed if a persistence layer is ever added.
    """

    audit_id: str
    goal: str
    status: Status
    reason: str | None
    iteration: int  # model calls made so far
    max_iterations: int
    remaining_iterations: int
    finding_ids: list[str]  # findings the agent may reason about
    evidence_ids: list[str]  # evidence those findings cite (references, not text)
    pending: dict[str, Any] | None  # validated decision awaiting execution
    steps: list[dict[str, Any]]  # ActionRecord dumps: what was done
    observations: list[dict[str, Any]]  # bounded tool results, newest last
    errors: list[str]  # safe error codes/messages
    invalid_streak: int
    finish_requested: bool
    model_summary: str | None
    result: dict[str, Any] | None


class ActionRecord(SchemaModel):
    step: int
    tool: str
    args: dict[str, Any]
    status: StepStatus
    error_code: str | None = None
    attempts: int = 1
    duration_ms: float = 0.0
    thought: str | None = None  # the model's stated reason, unverified


class AgentResult(VersionedRecord):
    """Explicit outcome of one agent run (``agent_trace.json``)."""

    audit_id: Identifier
    goal: str
    status: Literal["completed", "incomplete", "failed"]
    reason: str
    provider: str
    model_id: str
    iterations_used: int
    max_iterations: int
    steps: tuple[ActionRecord, ...]
    errors: tuple[str, ...]
    findings_total: int
    evidence_valid: bool
    output_valid: bool | None  # None: no recommendations were produced
    recommendations: RecommendationSet | None
    supplementary_evidence: tuple[EvidenceRef, ...]
    model_summary: str | None  # model-written, unvalidated
    started_at: UtcDatetime
    finished_at: UtcDatetime
