import json
import sqlite3

import pytest

from agent_system.agent import MAX_USER_MESSAGE_CHARS, AgentSystem, AgentTurnError
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel, ModelReply, ToolCall
from agent_system.tools import Tool, ToolRegistry, build_tools


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
    tool_events = [
        event for event in turn.trace if event["kind"] in {"tool", "observe"}
    ]
    assert tool_events[0]["tool_call_id"] == tool_events[1]["tool_call_id"]
    assert tool_events[2]["tool_call_id"] == tool_events[3]["tool_call_id"]
    assert tool_events[0]["tool_call_id"] != tool_events[2]["tool_call_id"]
    assert [event["tool_name"] for event in tool_events] == [
        "calculate",
        "calculate",
        "remember",
        "remember",
    ]


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


class DuplicateToolCallModel:
    name = "duplicate-tool-call"

    def complete(self, messages, tools):
        tool_results = [message for message in messages if message.get("role") == "tool"]
        if len(tool_results) < 2:
            return ModelReply(tool_calls=[ToolCall("stable-call-id", "increment", {})])
        return ModelReply(text="Finished without repeating the side effect.")


class ConflictingToolCallModel:
    name = "conflicting-tool-call"

    def complete(self, messages, tools):
        if not any(message.get("role") == "tool" for message in messages):
            return ModelReply(
                tool_calls=[ToolCall("reused-call-id", "remember", {"key": "state", "value": "one"})]
            )
        return ModelReply(
            tool_calls=[ToolCall("reused-call-id", "remember", {"key": "state", "value": "two"})]
        )


class OversizedToolBatchModel:
    name = "oversized-tool-batch"

    def complete(self, messages, tools):
        return ModelReply(
            tool_calls=[
                ToolCall("write-one", "remember", {"key": "first", "value": "one"}),
                ToolCall("write-two", "remember", {"key": "second", "value": "two"}),
            ]
        )


class DuplicateIdsInOneBatchModel:
    name = "duplicate-ids-in-one-batch"

    def complete(self, messages, tools):
        return ModelReply(
            tool_calls=[
                ToolCall("duplicate-id", "remember", {"key": "first", "value": "one"}),
                ToolCall("duplicate-id", "remember", {"key": "second", "value": "two"}),
            ]
        )


class OversizedToolArgumentsBatchModel:
    name = "oversized-tool-arguments-batch"

    def complete(self, messages, tools):
        return ModelReply(
            tool_calls=[
                ToolCall("small-write", "remember", {"key": "first", "value": "one"}),
                ToolCall(
                    "large-write",
                    "remember",
                    {"key": "second", "value": "x" * 1_000},
                ),
            ]
        )


class OversizedToolOutputModel:
    name = "oversized-tool-output"

    def __init__(self):
        self.tool_content = ""

    def complete(self, messages, tools):
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        if not tool_messages:
            return ModelReply(tool_calls=[ToolCall("large-read", "large_output", {})])
        self.tool_content = tool_messages[-1]["content"]
        return ModelReply(text="Handled the bounded tool result.")


def test_iteration_guardrail_stops_endless_tool_calls(tmp_path):
    agent = make_agent(tmp_path, model=EndlessModel(), max_iterations=2)
    turn = agent.run("keep going")

    assert turn.iterations == 2
    assert turn.tool_calls == 2
    assert "iteration limit" in turn.reply.lower()
    assert any(event["kind"] == "guardrail" for event in turn.trace)


def test_tool_call_budget_rejects_oversized_batch_before_side_effects(tmp_path):
    memory = MemoryStore(tmp_path / "state.db")
    agent = AgentSystem(
        model=OversizedToolBatchModel(),
        tools=build_tools(memory),
        memory=memory,
        max_tool_calls=1,
    )

    with pytest.raises(AgentTurnError, match="tool-call budget exceeded") as raised:
        agent.run("do too much at once")

    assert memory.recall() == []
    assert raised.value.turn["tool_calls"] == 0
    assert [event["kind"] for event in raised.value.turn["trace"]][-2:] == [
        "guardrail",
        "error",
    ]
    guardrail = raised.value.turn["trace"][-2]
    assert guardrail["detail"] == {"limit": 1, "remaining": 1, "requested": 2}
    assert memory.recent_turns()[0]["status"] == "failed"


def test_duplicate_ids_in_one_batch_are_rejected_before_side_effects(tmp_path):
    memory = MemoryStore(tmp_path / "state.db")
    agent = AgentSystem(
        model=DuplicateIdsInOneBatchModel(),
        tools=build_tools(memory),
        memory=memory,
    )

    with pytest.raises(AgentTurnError, match="duplicated in one model response") as raised:
        agent.run("reject an ambiguous batch")

    assert memory.recall() == []
    assert raised.value.turn["tool_calls"] == 0
    assert [event["kind"] for event in raised.value.turn["trace"]][-2:] == [
        "guardrail",
        "error",
    ]
    assert raised.value.turn["trace"][-2]["detail"] == {
        "reason": "duplicate tool call ID in one model response",
        "tool_call_id": "duplicate-id",
    }


def test_oversized_tool_arguments_reject_the_batch_before_side_effects(tmp_path):
    memory = MemoryStore(tmp_path / "state.db")
    agent = AgentSystem(
        model=OversizedToolArgumentsBatchModel(),
        tools=build_tools(memory),
        memory=memory,
        max_tool_argument_bytes=512,
    )

    with pytest.raises(AgentTurnError, match="arguments exceed 512 bytes") as raised:
        agent.run("reject a batch with oversized arguments")

    assert memory.recall() == []
    assert raised.value.turn["tool_calls"] == 0
    guardrail = raised.value.turn["trace"][-2]
    assert guardrail["kind"] == "guardrail"
    assert guardrail["title"] == "Tool arguments too large"
    assert guardrail["detail"]["limit_bytes"] == 512
    assert guardrail["detail"]["requested_bytes"] > 512
    assert guardrail["detail"]["tool_call_id"] == "large-write"


def test_oversized_tool_output_is_replaced_before_it_reaches_model_context(tmp_path):
    memory = MemoryStore(tmp_path / "state.db")
    tools = ToolRegistry()
    tools.register(
        Tool(
            name="large_output",
            description="Return a deliberately large test result.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            function=lambda: "x" * 1_000,
        )
    )
    model = OversizedToolOutputModel()
    agent = AgentSystem(
        model=model,
        tools=tools,
        memory=memory,
        max_tool_output_bytes=256,
    )

    turn = agent.run("bound the tool result")

    assert turn.reply == "Handled the bounded tool result."
    guardrail = next(event for event in turn.trace if event["kind"] == "guardrail")
    assert guardrail["title"] == "Tool output too large"
    assert guardrail["detail"]["limit_bytes"] == 256
    assert guardrail["detail"]["original_bytes"] > 1_000
    assert len(guardrail["detail"]["sha256"]) == 64
    observation = next(event for event in turn.trace if event["kind"] == "observe")
    assert observation["detail"]["ok"] is False
    assert observation["detail"]["original_bytes"] == guardrail["detail"]["original_bytes"]
    assert observation["detail"]["sha256"] == guardrail["detail"]["sha256"]
    assert json.loads(model.tool_content) == observation["detail"]
    assert "x" * 100 not in json.dumps(turn.to_dict())


def test_duplicate_tool_call_id_reuses_result_without_repeating_side_effect(tmp_path):
    executions = 0

    def increment():
        nonlocal executions
        executions += 1
        return executions

    memory = MemoryStore(tmp_path / "state.db")
    tools = ToolRegistry()
    tools.register(
        Tool(
            name="increment",
            description="Increment a test counter.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            function=increment,
        )
    )
    agent = AgentSystem(model=DuplicateToolCallModel(), tools=tools, memory=memory)

    turn = agent.run("run the increment once")

    assert executions == 1
    assert turn.tool_calls == 2
    assert [event["kind"] for event in turn.trace].count("deduplicate") == 1
    observations = [event["detail"] for event in turn.trace if event["kind"] == "observe"]
    assert observations == [{"ok": True, "result": 1}, {"ok": True, "result": 1}]


def test_reused_tool_call_id_with_different_input_fails_and_records_turn(tmp_path):
    agent = make_agent(tmp_path, model=ConflictingToolCallModel())

    with pytest.raises(RuntimeError, match="reused with different input"):
        agent.run("reject an ambiguous repeated call")

    assert agent.memory.recall("state")[0]["value"] == "one"
    failed_turn = agent.memory.recent_turns()[0]
    assert failed_turn["model"] == "conflicting-tool-call"
    assert failed_turn["status"] == "failed"
    assert "reused with different input" in failed_turn["error"]


def test_failed_turn_is_persisted_with_partial_tool_effects(tmp_path):
    agent = make_agent(tmp_path, model=FailingAfterWriteModel())

    with pytest.raises(AgentTurnError, match="provider disconnected") as raised:
        agent.run("remember this before failing")

    assert raised.value.turn["status"] == "failed"
    assert raised.value.turn["tool_calls"] == 1
    assert raised.value.turn["trace"][-1]["kind"] == "error"
    assert agent.memory.recall("partial")[0]["value"] == "saved"
    failed_turn = agent.memory.recent_turns()[0]
    assert failed_turn["model"] == "failing-after-write"
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
