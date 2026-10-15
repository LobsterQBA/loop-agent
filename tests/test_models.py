from types import SimpleNamespace

import pytest

from agent_system.agent import AgentSystem, AgentTurnError
from agent_system.memory import MemoryStore
from agent_system.models import LiveModel
from agent_system.tools import build_tools


class FakeCompletions:
    def __init__(self, *, arguments):
        function = SimpleNamespace(name="current_time", arguments=arguments)
        call = SimpleNamespace(id="call-1", function=function)
        message = SimpleNamespace(content="", tool_calls=[call])
        self.response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])

    def create(self, **kwargs):
        return self.response


def fake_live_model(arguments):
    model = LiveModel.__new__(LiveModel)
    model.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(arguments=arguments))
    )
    model.name = "fake-live-model"
    return model


def test_live_model_parses_object_tool_arguments():
    reply = fake_live_model('{"zone":"UTC"}').complete([], [])

    assert reply.tool_calls[0].arguments == {"zone": "UTC"}


def test_live_model_rejects_malformed_tool_arguments_without_echoing_payload():
    model = fake_live_model('{"secret":"do-not-log"')

    with pytest.raises(ValueError, match="returned invalid JSON arguments") as raised:
        model.complete([], [])

    assert "do-not-log" not in str(raised.value)


@pytest.mark.parametrize("arguments", ["[]", '"text"', "null", "7"])
def test_live_model_rejects_tool_arguments_that_are_not_objects(arguments):
    model = fake_live_model(arguments)

    with pytest.raises(TypeError, match="arguments must decode to an object"):
        model.complete([], [])


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
@pytest.mark.parametrize("with_tool_call", [False, True])
def test_live_model_rejects_incomplete_response_before_tool_execution(
    tmp_path, finish_reason, with_tool_call
):
    model = fake_live_model('{"key":"partial","value":"must not save"}')
    choice = model.client.chat.completions.response.choices[0]
    choice.finish_reason = finish_reason
    choice.message.content = "Partial response"
    choice.message.tool_calls[0].function.name = "remember"
    if not with_tool_call:
        choice.message.tool_calls = []
    memory = MemoryStore(tmp_path / "state.db")
    agent = AgentSystem(model=model, tools=build_tools(memory), memory=memory)

    with pytest.raises(AgentTurnError, match=finish_reason) as raised:
        agent.run("Remember a fact")

    turn = memory.turn(raised.value.turn["turn_id"])
    assert turn["status"] == "failed"
    assert turn["reply"] == ""
    assert turn["tool_calls"] == 0
    assert turn["trace"][-1]["kind"] == "error"
    assert memory.recall() == []


def test_live_model_accepts_normal_final_response():
    model = fake_live_model("{}")
    choice = model.client.chat.completions.response.choices[0]
    choice.finish_reason = "stop"
    choice.message.content = "Complete answer"
    choice.message.tool_calls = []

    assert model.complete([], []).text == "Complete answer"


@pytest.mark.parametrize(
    "arguments",
    [
        '{"key":"approved","value":"fact","key":"overwritten"}',
        '{"value":{"secret":"first","secret":"do-not-log"}}',
        '{"key":"same","key":"same"}',
    ],
)
def test_live_model_rejects_duplicate_argument_fields_without_echoing_payload(arguments):
    with pytest.raises(ValueError, match="duplicate JSON object fields") as raised:
        fake_live_model(arguments).complete([], [])

    assert "do-not-log" not in str(raised.value)
    assert "overwritten" not in str(raised.value)


def test_duplicate_fields_reject_entire_batch_before_memory_writes(tmp_path):
    model = fake_live_model('{"key":"first","value":"must not save"}')
    calls = model.client.chat.completions.response.choices[0].message.tool_calls
    calls[0].function.name = "remember"
    calls.append(SimpleNamespace(
        id="call-2",
        function=SimpleNamespace(
            name="remember",
            arguments='{"key":"approved","value":"fact","key":"overwritten"}',
        ),
    ))
    memory = MemoryStore(tmp_path / "state.db")
    agent = AgentSystem(model=model, tools=build_tools(memory), memory=memory)

    with pytest.raises(AgentTurnError, match="duplicate JSON object fields") as raised:
        agent.run("Remember these facts")

    assert memory.recall() == []
    turn = memory.turn(raised.value.turn["turn_id"])
    assert turn["status"] == "failed"
    assert turn["tool_calls"] == 0
    assert turn["trace"][-1]["kind"] == "error"
