"""A deliberately small and safe local tool registry."""

from __future__ import annotations

import ast
import json
import math
import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent_system.memory import MemoryStore

ToolFunction = Callable[..., Any]
MAX_CALCULATION_RESULT = 1_000_000_000_000


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    function: ToolFunction

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, arguments: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
        try:
            value = tool.function(**arguments)
            return json.dumps({"ok": True, "result": value}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - tool failures become model observations
            return json.dumps(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_calculate(expression: str) -> int | float:
    """Evaluate basic arithmetic without eval, names, calls, or attribute access."""

    if len(expression) > 100:
        raise ValueError("expression is too long")
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent is too large")
            result = _BINARY_OPERATORS[type(node.op)](left, right)
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](visit(node.operand))
        raise ValueError("only basic arithmetic is allowed")

    result = visit(tree)
    if not math.isfinite(result) or abs(result) > MAX_CALCULATION_RESULT:
        raise ValueError("result is too large")
    return result


def build_tools(memory: MemoryStore) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="calculate",
            description="Calculate a basic arithmetic expression safely.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Arithmetic expression"}
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            function=safe_calculate,
        )
    )
    registry.register(
        Tool(
            name="current_time",
            description="Read the current local date and time.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            function=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    )
    registry.register(
        Tool(
            name="remember",
            description="Save or update one durable local memory.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short memory label"},
                    "value": {"type": "string", "description": "Fact to remember"},
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
            function=memory.remember,
        )
    )
    registry.register(
        Tool(
            name="recall",
            description="Search durable local memory by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword or empty for recent"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            function=memory.recall,
        )
    )
    return registry
