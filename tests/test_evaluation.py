from agent_system.evaluation import evaluate_trace


def event(step, kind, elapsed_ms):
    return {"step": step, "kind": kind, "title": kind, "detail": {}, "elapsed_ms": elapsed_ms}


def tool_event(step, kind, elapsed_ms, call_id="call-1", tool_name="calculate"):
    value = event(step, kind, elapsed_ms)
    value.update({"tool_call_id": call_id, "tool_name": tool_name})
    return value


def test_completed_trace_passes_all_integrity_checks():
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "The answer is 42.",
            "iterations": 1,
            "tool_calls": 1,
            "trace": [
                event(1, "input", 0),
                event(2, "reason", 1),
                tool_event(3, "tool", 2),
                tool_event(4, "observe", 3),
                event(5, "reply", 4),
                event(6, "done", 5),
            ],
        }
    )

    assert evaluation["trace_integrity"] == "passed"
    assert evaluation["summary"] == {
        "checks_passed": 6,
        "checks_total": 6,
        "iterations": 1,
        "tool_calls": 1,
        "observations": 1,
        "duration_ms": 5,
    }


def test_evaluation_reports_each_trace_integrity_failure():
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "",
            "iterations": 0,
            "tool_calls": 1,
            "trace": [event(2, "tool", 8), event(3, "done", 4)],
        }
    )

    assert evaluation["trace_integrity"] == "failed"
    assert evaluation["summary"]["checks_passed"] == 2
    assert {check["name"] for check in evaluation["checks"] if not check["passed"]} == {
        "sequential_steps",
        "monotonic_timing",
        "tool_observations",
        "outcome_recorded",
    }


def test_failed_trace_uses_error_as_its_terminal_outcome():
    evaluation = evaluate_trace(
        {
            "status": "failed",
            "reply": "",
            "error": "RuntimeError: provider disconnected",
            "iterations": 0,
            "tool_calls": 0,
            "trace": [event(1, "input", 0), event(2, "error", 2)],
        }
    )

    assert evaluation["task_status"] == "failed"
    assert evaluation["trace_integrity"] == "passed"


def test_equal_tool_and_observation_counts_do_not_hide_bad_ordering():
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "done",
            "iterations": 0,
            "tool_calls": 2,
            "trace": [
                event(1, "tool", 0),
                event(2, "tool", 1),
                event(3, "observe", 2),
                event(4, "observe", 3),
                event(5, "done", 4),
            ],
        }
    )

    tool_check = next(
        check for check in evaluation["checks"] if check["name"] == "tool_observations"
    )
    assert tool_check["passed"] is False


def test_tool_observation_check_rejects_mismatched_call_identity():
    tool = tool_event(2, "tool", 1)
    observation = tool_event(3, "observe", 2, call_id="call-2")
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "done",
            "iterations": 0,
            "tool_calls": 1,
            "trace": [
                event(1, "input", 0),
                tool,
                observation,
                event(4, "done", 3),
            ],
        }
    )

    tool_check = next(
        check for check in evaluation["checks"] if check["name"] == "tool_observations"
    )
    assert tool_check["passed"] is False


def test_tool_observation_check_rejects_missing_call_identity():
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "done",
            "iterations": 0,
            "tool_calls": 1,
            "trace": [
                event(1, "input", 0),
                event(2, "tool", 1),
                event(3, "observe", 2),
                event(4, "done", 3),
            ],
        }
    )

    tool_check = next(
        check for check in evaluation["checks"] if check["name"] == "tool_observations"
    )
    assert tool_check["passed"] is False


def test_declared_count_check_rejects_metadata_that_disagrees_with_trace():
    evaluation = evaluate_trace(
        {
            "status": "completed",
            "reply": "done",
            "iterations": 2,
            "tool_calls": 0,
            "trace": [
                event(1, "input", 0),
                event(2, "reason", 1),
                tool_event(3, "tool", 2),
                tool_event(4, "observe", 3),
                event(5, "reply", 4),
                event(6, "done", 5),
            ],
        }
    )

    count_check = next(
        check for check in evaluation["checks"] if check["name"] == "declared_counts"
    )
    assert count_check["passed"] is False
    assert evaluation["summary"]["iterations"] == 1
    assert evaluation["summary"]["tool_calls"] == 1
