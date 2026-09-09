"""Model adapters.

DemoModel is deterministic and keyless, so anyone can watch a real tool loop.
LiveModel is optional and uses an OpenAI-compatible chat-completions endpoint.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class Model(Protocol):
    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply: ...


def _tool_call(name: str, **arguments) -> ModelReply:
    return ModelReply(tool_calls=[ToolCall(f"demo-{uuid4().hex[:8]}", name, arguments)])


def _tool_results(messages: list[dict]) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content", "{}"))
        except json.JSONDecodeError:
            payload = {"ok": False, "error": "invalid tool output"}
        results.setdefault(message.get("name", "unknown"), []).append(payload)
    return results


def _arithmetic_expression(text: str) -> str | None:
    normalized = text.replace("×", "*").replace("÷", "/")
    candidates = re.findall(r"(?<![\w.])[-+]?\d[\d\s.+\-*/%()]{1,60}", normalized)
    candidates = [candidate.strip().rstrip(".,?!") for candidate in candidates]
    candidates = [candidate for candidate in candidates if re.search(r"[+\-*/%]", candidate)]
    return max(candidates, key=len) if candidates else None


def _memory_key(text: str) -> str:
    match = re.search(r"(?:as|under|叫做|名为)\s+[\"']?([\w\- ]{2,40})", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(" .'\"")
    return "note"


class DemoModel:
    """A transparent rule-based planner for the no-key interactive demo."""

    name = "demo-planner"

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        user_message = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"), ""
        )
        lower = user_message.lower()
        results = _tool_results(messages)
        expression = _arithmetic_expression(user_message)

        wants_recall = any(
            phrase in lower
            for phrase in ("recall", "what do you remember", "memory", "你记得", "回忆")
        )
        wants_memory = (
            any(word in lower for word in ("remember", "save", "记住", "保存"))
            and not wants_recall
        )
        wants_time = any(phrase in lower for phrase in ("what time", "current time", "几点", "时间"))

        if expression and "calculate" not in results:
            return _tool_call("calculate", expression=expression)

        if wants_memory and "remember" not in results:
            if "calculate" in results:
                calculated = results["calculate"][-1]
                if not calculated.get("ok"):
                    return ModelReply(
                        text=f"Calculation failed: {calculated.get('error')}. "
                        "I did not save a result."
                    )
                value = str(calculated["result"])
            else:
                value = re.sub(
                    r"^(please\s+)?(remember|save)(\s+that)?\s+",
                    "",
                    user_message,
                    flags=re.IGNORECASE,
                ).strip()
                value = value or user_message
            return _tool_call("remember", key=_memory_key(user_message), value=value)

        if wants_recall and "recall" not in results:
            query = re.sub(
                r".*?(?:about|for|记得|关于)\s*", "", user_message, flags=re.IGNORECASE
            ).strip(" ?.!")
            return _tool_call("recall", query=query if len(query) < 80 else "")

        if wants_time and "current_time" not in results:
            return _tool_call("current_time")

        if results:
            summaries = []
            for tool_name, entries in results.items():
                latest = entries[-1]
                if not latest.get("ok"):
                    summaries.append(f"{tool_name} failed: {latest.get('error')}.")
                    continue
                result = latest.get("result")
                if tool_name == "calculate":
                    summaries.append(f"{expression} = {result}.")
                elif tool_name == "remember":
                    summaries.append(f"Saved “{result['key']}” = {result['value']}.")
                elif tool_name == "recall":
                    summaries.append(
                        "Found: " + "; ".join(f"{item['key']} = {item['value']}" for item in result)
                        if result else "No matching memories found."
                    )
                else:
                    summaries.append(f"Local time: {result}.")
            return ModelReply(text=" ".join(summaries))

        return ModelReply(
            text=(
                "Demo mode is ready. Ask me to calculate something, read the time, "
                "remember a fact, or recall one. The trace will show every step."
            )
        )


class LiveModel:
    """Optional adapter for an OpenAI-compatible function-calling model."""

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install live mode with: pip install -e '.[live]'") from exc
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.name = model

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        response = self.client.chat.completions.create(
            model=self.name,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(call.id, call.function.name, arguments))
        return ModelReply(text=message.content or "", tool_calls=calls)
