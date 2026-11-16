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
        "the current time display uses UTC",
        "the label is 时间",
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


@pytest.mark.parametrize("query", ["2026-11-02", "123-456", "3/4", "current time display", "时间"])
def test_recall_queries_remain_literal(tmp_path, query):
    agent = make_agent(tmp_path / "state.db")
    agent.memory.remember("saved fact", f"value for {query}")
    turn = agent.run(f"Recall {query}")

    assert f"value for {query}" in turn.reply
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["recall"]


@pytest.mark.parametrize("prompt", ["What time is it?", "Show the current time.", "现在几点？"])
def test_standalone_time_request_reads_clock(tmp_path, prompt):
    turn = make_agent(tmp_path / "state.db").run(prompt)
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["current_time"]
    assert turn.reply.startswith("Local time: ")


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


@pytest.mark.parametrize(
    ("prompt", "expected_tools"),
    [
        ("The screensaver is enabled", []),
        ("She remembers the setup", []),
        ("2 + 3 on the screensaver", ["calculate"]),
        ("Please save that the screensaver is enabled", ["remember"]),
        ("保存测试内容", ["remember"]),
    ],
)
def test_memory_write_requires_whole_english_command(tmp_path, prompt, expected_tools):
    agent = make_agent(tmp_path / "state.db")
    turn = agent.run(prompt)

    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == expected_tools
    assert bool(agent.memory.recall()) == ("remember" in expected_tools)


@pytest.mark.parametrize(
    "prompt",
    [
        "The current time display uses UTC.",
        "I wonder what time the meeting starts.",
        "What time does the store open?",
        "Show the current time format.",
        "Do not show the current time.",
        "时间管理很重要。",
        "会议几点开始？",
        "现在几点不重要。",
    ],
)
def test_clock_mentions_do_not_read_clock(tmp_path, prompt):
    turn = make_agent(tmp_path / "state.db").run(prompt)
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == []


@pytest.mark.parametrize(
    "prompt",
    [
        "  PLEASE show me the current time!  ",
        "What is the current time?",
        "Tell me the time, please.",
        "current time",
        "现在几点了？",
        "请告诉我现在的时间。",
        "时间",
    ],
)
def test_explicit_clock_request_variants(tmp_path, prompt):
    turn = make_agent(tmp_path / "state.db").run(prompt)
    assert [e["tool_name"] for e in turn.trace if e["kind"] == "tool"] == ["current_time"]
