import json
import sqlite3

import pytest

from agent_system.agent import AgentSystem
from agent_system.memory import MemoryStore
from agent_system.models import ModelReply, ToolCall
from agent_system.tools import Tool, ToolRegistry


def reject_constant(value):
    raise ValueError(f"non-JSON constant: {value}")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_output_is_observed_and_persisted_without_reexecution(tmp_path, value):
    memory = MemoryStore(tmp_path / "state.db")
    executions = []

    def save():
        executions.append("called")
        memory.remember("effect", "saved")
        return {"nested": [{"score": value}]}

    registry = ToolRegistry()
    registry.register(Tool("save", "Save a fact.", {"type": "object"}, save))
    observations = []

    class Model:
        name = "output-test"

        def complete(self, messages, tools):
            outputs = [message["content"] for message in messages if message["role"] == "tool"]
            if outputs:
                observations.append(json.loads(outputs[-1], parse_constant=reject_constant))
            if len(outputs) < 2:
                return ModelReply(tool_calls=[ToolCall("same-id", "save", {})])
            return ModelReply(text="The tool ran, but its output could not be encoded.")

    turn = AgentSystem(model=Model(), tools=registry, memory=memory).run("Save a fact.")
    assert executions == ["called"]
    assert memory.recall("effect")[0]["value"] == "saved"
    assert len(observations) == 2
    assert observations[0] == observations[1]
    assert observations[0]["ok"] is False
    assert "output" in observations[0]["error"]
    assert "ValueError" in observations[0]["error"]
    assert turn.status == "completed"  # The model can recover from a failed observation.
    assert sum(event["kind"] == "deduplicate" for event in turn.trace) == 1
    with sqlite3.connect(tmp_path / "state.db") as conn:
        raw_trace = conn.execute(
            "SELECT trace_json FROM turns WHERE id = ?", (turn.turn_id,)
        ).fetchone()[0]
    saved_trace = json.loads(raw_trace, parse_constant=reject_constant)
    assert [event["detail"] for event in saved_trace if event["kind"] == "observe"] == observations


def test_finite_nested_output_is_preserved():
    value = {"nested": [None, True, 0, -2.5, "你好", {"score": 1.25}]}
    registry = ToolRegistry()
    registry.register(Tool("value", "Return data.", {"type": "object"}, lambda: value))
    assert json.loads(registry.execute("value", {}), parse_constant=reject_constant) == {
        "ok": True,
        "result": value,
    }
