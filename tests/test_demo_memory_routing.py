import pytest

from agent_system.agent import AgentSystem
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel
from agent_system.tools import build_tools


def make_agent(path):
    memory = MemoryStore(path)
    return AgentSystem(model=DemoModel(), tools=build_tools(memory), memory=memory)


@pytest.mark.parametrize(
    "fact",
    [
        "the launch date is 2026-11-02",
        "the appointment is 11/02/2026",
        "the order number is 123-456",
        "the ratio is 3/4",
        "the formula is 2 + 3",
        "the memory limit is 2 GB",
        "the recall deadline is Friday",
        "the phrase is what do you remember",
    ],
)
def test_memory_facts_remain_literal_after_restart(tmp_path, fact):
    database = tmp_path / "state.db"
    agent = make_agent(database)
    turn = agent.run(f"Remember that {fact}")

    assert agent.memory.recall()[0]["value"] == fact
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["remember"]
    restarted = make_agent(database)
    recalled = restarted.run("Recall note")
    assert fact in recalled.reply
    assert restarted.memory.turn(turn.turn_id)["status"] == "completed"


@pytest.mark.parametrize("query", ["2026-11-02", "123-456", "3/4"])
def test_recall_numeric_queries_does_not_calculate(tmp_path, query):
    agent = make_agent(tmp_path / "state.db")
    agent.memory.remember("saved fact", f"value for {query}")
    turn = agent.run(f"Recall {query}")

    assert f"value for {query}" in turn.reply
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["recall"]


@pytest.mark.parametrize("prompt", ["2 + 3", "What is 2 + 3?"])
def test_standalone_arithmetic_still_calculates(tmp_path, prompt):
    turn = make_agent(tmp_path / "state.db").run(prompt)
    assert "= 5." in turn.reply
    assert turn.tool_calls == 1


@pytest.mark.parametrize("verb", ["Calculate", "Compute", "计算"])
def test_explicit_calculation_can_still_save_result(tmp_path, verb):
    agent = make_agent(tmp_path / "state.db")
    turn = agent.run(f"{verb} 2 + 3 and save as total.")
    assert agent.memory.recall("total")[0]["value"] == "5"
    assert turn.tool_calls == 2


def test_calculated_result_can_use_memory_in_its_key(tmp_path):
    agent = make_agent(tmp_path / "state.db")
    turn = agent.run("Calculate 2 + 3 and save as memory score.")
    assert agent.memory.recall("memory score")[0]["value"] == "5"
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["calculate", "remember"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Recall save preference",
        "Please recall save preference",
        "Memory save preference",
        "What do you remember about save preference?",
    ],
)
def test_recall_query_with_save_word_does_not_write(tmp_path, prompt):
    agent = make_agent(tmp_path / "state.db")
    agent.memory.remember("save preference", "Keep the original")
    before = agent.memory.recall()
    turn = agent.run(prompt)
    assert "Keep the original" in turn.reply
    assert agent.memory.recall() == before
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["recall"]
