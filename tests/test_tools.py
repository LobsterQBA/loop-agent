import json
import sqlite3

import pytest

from agent_system.memory import MemoryStore
from agent_system.tools import build_tools, safe_calculate


def test_calculator_handles_basic_arithmetic():
    assert safe_calculate("17 * 23") == 391
    assert safe_calculate("(12 + 8) / 4") == 5


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('echo nope')", "open('/etc/passwd')", "2 ** 999", "True + 1"],
)
def test_calculator_rejects_unsafe_or_unbounded_input(expression):
    with pytest.raises((ValueError, SyntaxError)):
        safe_calculate(expression)


@pytest.mark.parametrize("expression", ["1000000000001", "1e309", "9" * 90])
def test_calculator_rejects_out_of_range_numeric_literals(expression):
    with pytest.raises(ValueError, match="result is too large"):
        safe_calculate(expression)


def test_calculator_rejects_complex_results():
    with pytest.raises(ValueError, match="result must be a real number"):
        safe_calculate("(-1) ** 0.5")


def test_tool_registry_surfaces_errors_as_data(tmp_path):
    registry = build_tools(MemoryStore(tmp_path / "state.db"))
    output = json.loads(registry.execute("calculate", {"expression": "1 / 0"}))
    assert output["ok"] is False
    assert "ZeroDivisionError" in output["error"]


def test_memory_is_durable(tmp_path):
    path = tmp_path / "state.db"
    MemoryStore(path).remember("launch score", "391")
    reopened = MemoryStore(path)
    assert reopened.recall("launch")[0]["value"] == "391"


def test_memory_migrates_existing_turn_ledgers(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE turns (
                id INTEGER PRIMARY KEY,
                user_message TEXT NOT NULL,
                reply TEXT NOT NULL,
                mode TEXT NOT NULL,
                iterations INTEGER NOT NULL,
                trace_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.execute(
            """INSERT INTO turns (user_message, reply, mode, iterations, trace_json)
            VALUES ('hello', 'hi', 'demo', 1, '[]')"""
        )

    memory = MemoryStore(path)

    assert memory.recent_turns()[0]["status"] == "completed"
    assert memory.recent_turns()[0]["error"] is None


@pytest.mark.parametrize(
    ("query", "matching_key"),
    [("%", "conversion %"), ("_", "feature_name")],
)
def test_memory_search_treats_like_metacharacters_literally(tmp_path, query, matching_key):
    memory = MemoryStore(tmp_path / "state.db")
    memory.remember("ordinary note", "no special characters")
    memory.remember(matching_key, "matched")

    assert [item["key"] for item in memory.recall(query)] == [matching_key]
