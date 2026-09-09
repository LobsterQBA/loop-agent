"""Run the portfolio example in fresh processes without keys or persistent app state."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A fresh interpreter per turn rules out in-process state as the source of recall.
_WORKER = """
import json
import sys
from agent_system.agent import AgentSystem
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel
from agent_system.tools import build_tools
memory = MemoryStore(sys.argv[1])
agent = AgentSystem(model=DemoModel(), tools=build_tools(memory), memory=memory)
turn = agent.run(sys.argv[2])
print(json.dumps({"turn": turn.to_dict(), "memories": memory.recall()}))
"""


def run_turn(database: Path, message: str) -> dict:
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-c", _WORKER, str(database), message],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    return json.loads(result.stdout)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    with TemporaryDirectory(prefix="loop-agent-walkthrough-") as folder:
        database = Path(folder) / "state.db"
        first = run_turn(
            database, "Calculate 17 * 23 and remember the result as launch score."
        )
        require(first["turn"]["iterations"] == 3, "Expected three planner calls")
        require(first["turn"]["tool_calls"] == 2, "Expected two tool calls")
        require(
            any(m["key"] == "launch score" and m["value"] == "391" for m in first["memories"]),
            "Expected launch score = 391",
        )
        print("PASS calculate + remember: 391; 3 planner calls; 2 tool calls")
        second = run_turn(database, "What do you remember about launch score?")
        observed = [e["detail"] for e in second["turn"]["trace"] if e["kind"] == "observe"]
        require(
            any(
                item["key"] == "launch score" and item["value"] == "391"
                for event in observed if event.get("ok")
                for item in event["result"]
            ),
            "Fresh process did not recall the saved value",
        )
        print("PASS restart + recall: launch score = 391 in a fresh process")
        third = run_turn(
            database, "Calculate 1 / 0 and remember the result as invalid score."
        )
        require(third["memories"] == first["memories"], "Failed calculation changed memory")
        require(third["turn"]["tool_calls"] == 1, "Failed calculation should not write memory")
        require(
            any(e["kind"] == "observe" and not e["detail"]["ok"] for e in third["turn"]["trace"]),
            "Expected a structured tool error",
        )
        print("PASS failed calculation: error observed; no memory written")
    print("PASS all checks; temporary state removed")


if __name__ == "__main__":
    main()
