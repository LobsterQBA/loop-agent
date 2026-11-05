import json

import pytest

from agent_system.agent import AgentSystem, AgentTurnError
from agent_system.memory import MemoryStore
from agent_system.models import ModelReply, ToolCall
from agent_system.tools import build_tools


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("after_write", [False, True])
@pytest.mark.parametrize("detail", ["provider: \ud800 / \udfff", "服务暂不可用 🌍"])
def test_exception_text_keeps_failed_turn_readable(tmp_path, exception_type, after_write, detail):
    failure = exception_type(detail)

    class FailingModel:
        name = "failing-provider"

        def complete(self, messages, tools):
            if after_write and not any(message["role"] == "tool" for message in messages):
                return ModelReply(
                    tool_calls=[ToolCall("save", "remember", {"key": "partial", "value": "saved"})]
                )
            raise failure

    path = tmp_path / "state.db"
    memory = MemoryStore(path)
    agent = AgentSystem(model=FailingModel(), tools=build_tools(memory), memory=memory)
    expected_type = KeyboardInterrupt if exception_type is KeyboardInterrupt else AgentTurnError
    with pytest.raises(expected_type) as raised:
        agent.run("Run the task")

    expected_error = f"{exception_type.__name__}: {detail}".encode(
        "utf-8", errors="backslashreplace"
    ).decode("utf-8")
    reopened = MemoryStore(path)
    summary = reopened.recent_turns()[0]
    turn = reopened.turn(summary["id"])
    assert turn["status"] == "failed"
    assert turn["error"] == summary["error"] == expected_error
    assert turn["trace"][-1]["detail"] == {"error": expected_error}
    assert turn["iterations"] == (2 if after_write else 1)
    assert turn["tool_calls"] == int(after_write)
    assert bool(reopened.recall("partial")) is after_write
    json.dumps(turn, ensure_ascii=False).encode("utf-8")
    if exception_type is KeyboardInterrupt:
        assert raised.value is failure
    else:
        assert raised.value.__cause__ is failure
        assert raised.value.turn["trace"] == turn["trace"]
        assert raised.value.turn["error"] == expected_error


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("after_write", [False, True])
def test_unprintable_exception_preserves_failure_and_partial_effects(
    tmp_path, exception_type, after_write
):
    class UnprintableError(exception_type):
        def __str__(self):
            raise ValueError("formatting failed: private provider details")

    failure = UnprintableError()

    class FailingModel:
        name = "unprintable-provider"

        def complete(self, messages, tools):
            if after_write and not any(message["role"] == "tool" for message in messages):
                return ModelReply(
                    tool_calls=[ToolCall("save", "remember", {"key": "partial", "value": "saved"})]
                )
            raise failure

    path = tmp_path / "state.db"
    memory = MemoryStore(path)
    agent = AgentSystem(model=FailingModel(), tools=build_tools(memory), memory=memory)
    expected_type = KeyboardInterrupt if exception_type is KeyboardInterrupt else AgentTurnError
    with pytest.raises(expected_type) as raised:
        agent.run("Run the task")

    reopened = MemoryStore(path)
    summary = reopened.recent_turns()[0]
    turn = reopened.turn(summary["id"])
    expected_error = "UnprintableError: <exception message unavailable>"
    assert turn["error"] == summary["error"] == expected_error
    assert turn["status"] == "failed"
    assert turn["trace"][-1]["detail"] == {"error": expected_error}
    assert turn["iterations"] == (2 if after_write else 1)
    assert turn["tool_calls"] == int(after_write)
    assert bool(reopened.recall("partial")) is after_write
    assert "private provider details" not in json.dumps(turn)
    if exception_type is KeyboardInterrupt:
        assert raised.value is failure
    else:
        assert raised.value.__cause__ is failure
        assert raised.value.turn["trace"] == turn["trace"]
