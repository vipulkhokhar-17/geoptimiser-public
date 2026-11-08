"""Graph nodes and routing, as plain functions over ``AgentState``.

This module has no LangGraph dependency: ``graph.py`` only wires these functions into a
``StateGraph``. Keeping the logic here makes every transition unit-testable.

Control rules (none of them can be changed by model output or website text):
* the model is called at most ``max_iterations`` times;
* only registry tools run, with validated arguments, under a timeout;
* only *transient* failures are retried, a bounded number of times;
* the final status comes from deterministic validation, not from the model's claim.
"""

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any

from geoptimiser.agent.config import AgentConfig
from geoptimiser.agent.models import AgentModel, ChatMessage, ModelError
from geoptimiser.agent.prompt import (
    FINISH,
    DecisionError,
    build_messages,
    canonical_args,
    parse_decision,
)
from geoptimiser.agent.state import ActionRecord, AgentResult, AgentState
from geoptimiser.agent.tools import AgentContext, ToolError, ToolRegistry
from geoptimiser.recommendations import validate_recommendations

log = logging.getLogger("geoptimiser.agent")
_MAX_ARG_CHARS = 400
_MAX_ERRORS = 50


def _emit(event: str, **fields: Any) -> None:
    """One structured log line. Callers pass codes, counts and timings, never content."""
    log.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _bounded_args(args: dict[str, Any]) -> dict[str, Any]:
    return args if len(canonical_args(args)) <= _MAX_ARG_CHARS else {"_truncated": True}


# --- routing (pure) -------------------------------------------------------------------


def route_after_inspect(state: AgentState) -> str:
    if state["status"] != "running" or state["finish_requested"]:
        return "finalize"  # failed already, or nothing to investigate
    return "decide"


def route_after_decide(state: AgentState) -> str:
    if state["status"] != "running" or state["finish_requested"]:
        return "finalize"
    return "act" if state["pending"] is not None else "decide"


def route_after_act(state: AgentState) -> str:
    if state["status"] != "running":
        return "finalize"
    return "finalize" if state["iteration"] >= state["max_iterations"] else "decide"


def initial_state(audit_id: str, goal: str, max_iterations: int) -> AgentState:
    return AgentState(
        audit_id=audit_id,
        goal=goal,
        status="running",
        reason=None,
        iteration=0,
        max_iterations=max_iterations,
        remaining_iterations=max_iterations,
        finding_ids=[],
        evidence_ids=[],
        pending=None,
        steps=[],
        observations=[],
        errors=[],
        invalid_streak=0,
        finish_requested=False,
        model_summary=None,
        result=None,
    )


class AgentRuntime:
    """Holds the live collaborators and implements the graph's nodes."""

    def __init__(
        self,
        *,
        context: AgentContext,
        registry: ToolRegistry,
        model: AgentModel,
        config: AgentConfig,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ctx, self.registry, self.model = context, registry, model
        self.config, self.sleep, self.clock, self.monotonic = (
            config,
            sleep,
            clock,
            monotonic,
        )
        self.started_at = clock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-tool")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- nodes ---------------------------------------------------------------------

    def inspect(self, state: AgentState) -> dict[str, Any]:
        """Read the existing audit state; no model call, no tool call."""
        findings = self.ctx.diagnosis.findings
        evidence = sorted({e for f in findings for e in f.evidence_ids})
        _emit(
            "inspect",
            audit_id=state["audit_id"],
            findings=len(findings),
            evidence=len(evidence),
        )
        update: dict[str, Any] = {
            "finding_ids": [f.finding_id for f in findings],
            "evidence_ids": evidence,
        }
        if not findings:
            update |= {"status": "running", "finish_requested": True}
        return update

    def decide(self, state: AgentState) -> dict[str, Any]:
        if state["iteration"] >= state["max_iterations"]:
            return self._stop("incomplete", "iteration_budget_exhausted")
        messages = self._messages(state)
        started = self.monotonic()
        reply, failure = self._call_model(messages)
        iteration = state["iteration"] + 1
        base: dict[str, Any] = {
            "iteration": iteration,
            "remaining_iterations": state["max_iterations"] - iteration,
        }
        if failure is not None:
            _emit(
                "model_failed",
                audit_id=state["audit_id"],
                step=iteration,
                error=failure,
            )
            return base | self._stop("failed", f"model_error: {failure}")
        _emit(
            "model_reply",
            audit_id=state["audit_id"],
            step=iteration,
            duration_ms=round((self.monotonic() - started) * 1000, 1),
            chars=len(reply or ""),
        )
        try:
            decision = parse_decision(reply or "")
        except DecisionError as exc:
            return base | self._invalid(
                state, iteration, "(unparsed)", {}, "invalid", str(exc)
            )
        thought = _clip(decision.thought, 300) if decision.thought else None
        if decision.action == FINISH:
            return base | {
                "pending": None,
                "finish_requested": True,
                "invalid_streak": 0,
                "model_summary": _clip(decision.summary or "", 1000) or None,
                "steps": [
                    *state["steps"],
                    self._record(iteration, FINISH, {}, "ok", thought=thought),
                ],
            }
        if decision.action not in self.registry:
            return base | self._invalid(
                state, iteration, decision.action, {}, "rejected",
                f"unauthorized_tool: {_clip(decision.action, 40)!r} is not an allowed tool",
                thought,
            )  # fmt: skip
        key = (decision.action, canonical_args(decision.args))
        if any((s["tool"], canonical_args(s["args"])) == key and s["status"] == "ok"
               for s in state["steps"]):  # fmt: skip
            return base | self._invalid(
                state, iteration, decision.action, _bounded_args(decision.args), "rejected",
                "duplicate_action: this exact call already succeeded; use its earlier result",
                thought,
            )  # fmt: skip
        return base | {
            "pending": {
                "tool": decision.action,
                "args": decision.args,
                "thought": thought,
            },
            "invalid_streak": 0,
        }

    def act(self, state: AgentState) -> dict[str, Any]:
        pending = state["pending"]
        assert pending is not None
        tool, args, step = pending["tool"], pending["args"], state["iteration"]
        started = self.monotonic()
        status, code, attempts, payload = self._execute(tool, args)
        duration = (self.monotonic() - started) * 1000
        ok = status == "ok"
        content = json.dumps(payload, sort_keys=True, default=str)
        content = _clip(content, self.config.max_observation_chars)
        _emit(
            "tool", audit_id=state["audit_id"], step=step, tool=tool, status=status,
            error_code=code, attempts=attempts, duration_ms=round(duration, 1),
        )  # fmt: skip
        record = self._record(
            step,
            tool,
            _bounded_args(args),
            status,
            code,
            attempts,
            duration,
            pending["thought"],
        )
        window = self.config.history_window
        errors = (
            state["errors"]
            if ok
            else [*state["errors"], f"{tool}: {code}"][-_MAX_ERRORS:]
        )
        return {
            "pending": None,
            "steps": [*state["steps"], record],
            "observations": [
                *state["observations"],
                {"step": step, "tool": tool, "ok": ok, "content": content},
            ][-window:],
            "errors": errors,
        }

    def finalize(self, state: AgentState) -> dict[str, Any]:
        """Decide the outcome from validation, not from what the model said."""
        status, reason = state["status"], state["reason"]
        ctx = self.ctx
        diagnosis_problems = ctx.problems()
        recs = ctx.recommendations
        recs_problems = (
            validate_recommendations(recs, ctx.diagnosis) if recs is not None else None
        )
        if status == "running":
            if diagnosis_problems:
                status, reason = "failed", "evidence_validation_failed"
            elif not state["finding_ids"]:
                status, reason = "completed", "no_findings: nothing to recommend"
            elif not state["finish_requested"]:
                status = "incomplete"
                reason = (
                    "iteration_budget_exhausted"
                    if state["iteration"] >= state["max_iterations"]
                    else "stopped_before_finishing"
                )
            elif recs is None:
                status, reason = "incomplete", "finished_without_recommendations"
            elif recs_problems:
                status, reason = "failed", "recommendation_validation_failed"
            elif not recs.recommendations:
                status, reason = "incomplete", "no_recommendation_could_be_issued"
            else:
                status, reason = "completed", "recommendations_validated"
        elif status == "incomplete" and diagnosis_problems:
            status, reason = "failed", "evidence_validation_failed"
        result = AgentResult(
            audit_id=state["audit_id"],
            goal=state["goal"],
            status=status,  # type: ignore[arg-type]
            reason=reason or status,
            provider=self.model.provider,
            model_id=self.model.model_id,
            iterations_used=state["iteration"],
            max_iterations=state["max_iterations"],
            steps=tuple(ActionRecord.model_validate(s) for s in state["steps"]),
            errors=tuple(state["errors"]),
            findings_total=len(state["finding_ids"]),
            evidence_valid=not diagnosis_problems,
            output_valid=None if recs is None else not recs_problems,
            recommendations=recs,
            supplementary_evidence=tuple(
                r for refs in ctx.supplementary.values() for r in refs
            ),
            model_summary=state["model_summary"],
            started_at=self.started_at,
            finished_at=self.clock(),
        )
        _emit("finish", audit_id=state["audit_id"], status=status, reason=reason,
              iterations=state["iteration"])  # fmt: skip
        return {
            "status": status,
            "reason": reason,
            "result": result.model_dump(mode="json"),
        }

    # --- helpers -------------------------------------------------------------------

    def _stop(self, status: str, reason: str) -> dict[str, Any]:
        return {"status": status, "reason": reason, "pending": None}

    def _messages(self, state: AgentState) -> list[ChatMessage]:
        return build_messages(
            goal=state["goal"],
            audit_id=state["audit_id"],
            described_tools=self.registry.describe(),
            findings_total=len(state["finding_ids"]),
            remaining=state["remaining_iterations"],
            steps=state["steps"],
            observations=state["observations"],
            errors=state["errors"],
        )

    def _call_model(self, messages: list[ChatMessage]) -> tuple[str | None, str | None]:
        """(reply, None) or (None, safe failure); retries transient errors only."""
        attempt = 0
        while True:
            try:
                return self.model.complete(messages), None
            except ModelError as exc:
                if exc.transient and attempt < self.config.max_model_retries:
                    attempt += 1
                    self.sleep(self.config.retry_delay_seconds * attempt)
                    continue
                return (
                    None,
                    f"{'transient, retries exhausted' if exc.transient else 'permanent'}: {exc}"[
                        :200
                    ],
                )

    def _record(
        self, step: int, tool: str, args: dict[str, Any], status: str,
        code: str | None = None, attempts: int = 1, duration_ms: float = 0.0,
        thought: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        return ActionRecord(
            step=step, tool=tool, args=args, status=status,  # type: ignore[arg-type]
            error_code=code, attempts=attempts, duration_ms=round(duration_ms, 1),
            thought=thought,
        ).model_dump()  # fmt: skip

    def _invalid(
        self, state: AgentState, step: int, tool: str, args: dict[str, Any],
        status: str, message: str, thought: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        streak = state["invalid_streak"] + 1
        code = message.split(":", 1)[0]
        _emit(
            "invalid_decision",
            audit_id=state["audit_id"],
            step=step,
            code=code,
            streak=streak,
        )
        update: dict[str, Any] = {
            "pending": None,
            "invalid_streak": streak,
            "steps": [
                *state["steps"],
                self._record(step, tool, args, status, code, 1, 0, thought),
            ],
            "errors": [*state["errors"], f"decision: {message}"][-_MAX_ERRORS:],
            "observations": [
                *state["observations"],
                {
                    "step": step,
                    "tool": tool,
                    "ok": False,
                    "content": json.dumps({"error": message}),
                },
            ][-self.config.history_window :],
        }
        if streak >= self.config.max_invalid_decisions:
            update |= self._stop("failed", "model_protocol_violation")
        return update

    def _execute(
        self, tool: str, args: dict[str, Any]
    ) -> tuple[str, str | None, int, dict[str, Any]]:
        """Validate and run one tool: (status, error_code, attempts, payload)."""
        try:
            parsed = self.registry.validate(tool, args)
        except ToolError as exc:
            return "rejected", exc.code, 0, {"error": str(exc)}
        attempts = 0
        while True:
            attempts += 1
            future = self._pool.submit(self.registry.run, tool, parsed, self.ctx)
            try:
                return (
                    "ok",
                    None,
                    attempts,
                    future.result(timeout=self.config.tool_timeout_seconds),
                )
            except FutureTimeout:
                future.cancel()
                # A timed-out call is not retried: the worker may still be running.
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="agent-tool"
                )
                return "timeout", "timeout", attempts, {"error": "tool timed out"}
            except ToolError as exc:
                if exc.transient and attempts <= self.config.max_tool_retries:
                    self.sleep(self.config.retry_delay_seconds * attempts)
                    continue
                return "error", exc.code, attempts, {"error": str(exc)}
            except Exception as exc:  # a tool bug must not end the run
                return "error", "tool_crashed", attempts, {"error": type(exc).__name__}
