"""Deterministic integrity checks for persisted agent traces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_trace(turn: Mapping[str, Any]) -> dict:
    """Evaluate whether a turn's execution trace is internally consistent.

    These checks evaluate recorded evidence, not whether the model's answer was
    useful or correct. They are deterministic and require no model call.
    """
    trace = turn.get("trace")
    events = trace if isinstance(trace, list) else []
    status = turn.get("status", "completed")
    tool_calls = sum(
        isinstance(event, dict) and event.get("kind") == "tool" for event in events
    )
    observations = sum(
        isinstance(event, dict) and event.get("kind") == "observe" for event in events
    )
    pending_tool = False
    tool_sequence_valid = True
    for event in events:
        kind = event.get("kind") if isinstance(event, dict) else None
        if kind == "tool":
            if pending_tool:
                tool_sequence_valid = False
            pending_tool = True
        elif kind == "observe":
            if not pending_tool:
                tool_sequence_valid = False
            pending_tool = False

    steps = [event.get("step") for event in events if isinstance(event, dict)]
    elapsed = [event.get("elapsed_ms") for event in events if isinstance(event, dict)]
    expected_terminal = "error" if status == "failed" else "done"
    actual_terminal = events[-1].get("kind") if events and isinstance(events[-1], dict) else None

    checks = [
        {
            "name": "sequential_steps",
            "passed": steps == list(range(1, len(events) + 1)),
            "detail": "Trace steps are contiguous and start at 1.",
        },
        {
            "name": "monotonic_timing",
            "passed": all(isinstance(value, int | float) and value >= 0 for value in elapsed)
            and elapsed == sorted(elapsed),
            "detail": "Elapsed times are non-negative and never move backwards.",
        },
        {
            "name": "tool_observations",
            "passed": tool_calls == observations and tool_sequence_valid and not pending_tool,
            "detail": f"Recorded {tool_calls} tool call(s) and {observations} observation(s).",
        },
        {
            "name": "terminal_event",
            "passed": actual_terminal == expected_terminal,
            "detail": f"A {status} turn must end with a {expected_terminal!r} event.",
        },
        {
            "name": "outcome_recorded",
            "passed": bool(turn.get("error")) if status == "failed" else bool(turn.get("reply")),
            "detail": "The persisted turn includes the outcome expected for its status.",
        },
    ]
    passed = sum(check["passed"] for check in checks)
    duration_ms = elapsed[-1] if elapsed and isinstance(elapsed[-1], int | float) else None
    return {
        "task_status": status,
        "trace_integrity": "passed" if passed == len(checks) else "failed",
        "summary": {
            "checks_passed": passed,
            "checks_total": len(checks),
            "tool_calls": tool_calls,
            "observations": observations,
            "duration_ms": duration_ms,
        },
        "checks": checks,
    }
