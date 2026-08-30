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


def test_iteration_guardrail_stops_endless_tool_calls(tmp_path):
    agent = make_agent(tmp_path, model=EndlessModel(), max_iterations=2)
    turn = agent.run("keep going")

    assert turn.iterations == 2
    assert turn.tool_calls == 2
    assert "iteration limit" in turn.reply.lower()
    assert any(event["kind"] == "guardrail" for event in turn.trace)


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
