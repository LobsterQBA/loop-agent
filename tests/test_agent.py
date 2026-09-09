import json
import sqlite3

import pytest

from agent_system.agent import MAX_USER_MESSAGE_CHARS, AgentSystem
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel, ModelReply, ToolCall
from agent_system.tools import build_tools


def make_agent(tmp_path, model=None, max_iterations=6):
    memory = MemoryStore(tmp_path / "state.db")
    return AgentSystem(
        model=model or DemoModel(),
        tools=build_tools(memory),
        memory=memory,
        max_iterations=max_iterations,
    )


def test_demo_agent_chains_calculate_and_remember(tmp_path):
    agent = make_agent(tmp_path)
    turn = agent.run("Calculate 17 × 23 and remember the result as launch score.")

    assert turn.tool_calls == 2
    assert turn.iterations == 3
    assert "Saved “launch score” = 391." in turn.reply
    assert agent.memory.recall("launch score")[0]["value"] == "391"
    assert [event["kind"] for event in turn.trace].count("tool") == 2
    assert turn.trace[-1]["kind"] == "done"


def test_demo_agent_recalls_saved_memory(tmp_path):
    agent = make_agent(tmp_path)
    agent.memory.remember("posting preference", "Keep LinkedIn posts concise")
    turn = agent.run("What do you remember about posting preference?")

    assert turn.tool_calls == 1
    assert "Keep LinkedIn posts concise" in turn.reply


class EndlessModel:
    name = "endless-test-model"

    def complete(self, messages, tools):
        return ModelReply(tool_calls=[ToolCall("loop", "current_time", {})])


class FailingAfterWriteModel:
    name = "failing-after-write"

    def complete(self, messages, tools):
        if not any(message.get("role") == "tool" for message in messages):
            return ModelReply(
                tool_calls=[ToolCall("write", "remember", {"key": "partial", "value": "saved"})]
            )
        raise RuntimeError("provider disconnected")


def test_iteration_guardrail_stops_endless_tool_calls(tmp_path):
    agent = make_agent(tmp_path, model=EndlessModel(), max_iterations=2)
    turn = agent.run("keep going")

    assert turn.iterations == 2
    assert turn.tool_calls == 2
    assert "iteration limit" in turn.reply.lower()
    assert any(event["kind"] == "guardrail" for event in turn.trace)


def test_failed_turn_is_persisted_with_partial_tool_effects(tmp_path):
    agent = make_agent(tmp_path, model=FailingAfterWriteModel())

    with pytest.raises(RuntimeError, match="provider disconnected"):
        agent.run("remember this before failing")

    assert agent.memory.recall("partial")[0]["value"] == "saved"
    failed_turn = agent.memory.recent_turns()[0]
    assert failed_turn["status"] == "failed"
    assert failed_turn["reply"] == ""
    assert failed_turn["iterations"] == 2
    assert failed_turn["error"] == "RuntimeError: provider disconnected"
    with sqlite3.connect(agent.memory.path) as conn:
        trace = json.loads(conn.execute("SELECT trace_json FROM turns").fetchone()[0])
    assert [event["kind"] for event in trace][-2:] == ["reason", "error"]
    assert any(event["kind"] == "observe" for event in trace)


def test_empty_message_is_rejected(tmp_path):
    agent = make_agent(tmp_path)
    try:
        agent.run("   ")
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("empty message should be rejected")


def test_agent_rejects_messages_beyond_the_public_limit(tmp_path):
    agent = make_agent(tmp_path)

    with pytest.raises(ValueError, match="at most 2000 characters"):
        agent.run("x" * (MAX_USER_MESSAGE_CHARS + 1))


@pytest.mark.parametrize("prior_value", [None, "valid previous result"])
def test_failed_calculation_does_not_write_memory(tmp_path, prior_value):
    agent = make_agent(tmp_path)
    if prior_value is not None:
        agent.memory.remember("invalid score", prior_value)
    before = agent.memory.recall()

    turn = agent.run("Calculate 1 / 0 and remember the result as invalid score.")

    assert turn.tool_calls == 1
    assert "did not save" in turn.reply
    assert agent.memory.recall() == before
    observations = [event["detail"] for event in turn.trace if event["kind"] == "observe"]
    assert observations[0]["ok"] is False
    assert "ZeroDivisionError" in observations[0]["error"]
    assert agent.memory.recent_turns()[0]["reply"] == turn.reply
