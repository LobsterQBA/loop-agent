"""The whole agent turn: reason, act, observe, repeat, then persist."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from agent_system.memory import MemoryStore
from agent_system.models import Model
from agent_system.tools import ToolRegistry

SYSTEM_PROMPT = """You are Loop Agent, a concise local assistant.
Use tools when they are useful. Never claim a tool succeeded until you read its result.
The available tools are deliberately local and safe: arithmetic, time, remember, and recall.
When the task is complete, answer clearly and briefly."""
MAX_USER_MESSAGE_CHARS = 2_000


@dataclass(frozen=True)
class AgentTurn:
    reply: str
    trace: list[dict]
    iterations: int
    tool_calls: int
    mode: str
    model: str
    turn_id: int

    def to_dict(self) -> dict:
        return asdict(self)


class AgentTurnError(RuntimeError):
    """A failed turn whose persisted execution evidence can still be returned."""

    def __init__(
        self,
        message: str,
        *,
        trace: list[dict],
        iterations: int,
        tool_calls: int,
        mode: str,
        model: str,
        turn_id: int,
    ):
        super().__init__(message)
        self.turn = {
            "reply": "",
            "trace": trace,
            "iterations": iterations,
            "tool_calls": tool_calls,
            "mode": mode,
            "model": model,
            "turn_id": turn_id,
            "status": "failed",
            "error": message,
        }


class AgentSystem:
    def __init__(
        self,
        *,
        model: Model,
        tools: ToolRegistry,
        memory: MemoryStore,
        mode: str = "demo",
        max_iterations: int = 6,
    ):
        self.model = model
        self.tools = tools
        self.memory = memory
        self.mode = mode
        self.max_iterations = max(1, min(max_iterations, 12))

    def run(self, user_message: str) -> AgentTurn:
        user_message = " ".join(user_message.strip().split())
        if not user_message:
            raise ValueError("message must not be empty")
        if len(user_message) > MAX_USER_MESSAGE_CHARS:
            raise ValueError(f"message must be at most {MAX_USER_MESSAGE_CHARS} characters")

        started = time.perf_counter()
        trace: list[dict] = []
        tool_call_count = 0
        tool_results_by_call_id: dict[str, tuple[str, str, str]] = {}

        def emit(kind: str, title: str, detail) -> None:
            trace.append(
                {
                    "step": len(trace) + 1,
                    "kind": kind,
                    "title": title,
                    "detail": detail,
                    "elapsed_ms": round((time.perf_counter() - started) * 1_000),
                }
            )

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        emit("input", "Turn started", user_message)

        reply = ""
        iterations = 0
        try:
            for iteration in range(1, self.max_iterations + 1):
                iterations = iteration
                emit("reason", f"Model call · iteration {iteration}", {"model": self.model.name})
                model_reply = self.model.complete(messages, self.tools.schemas())

                if not model_reply.tool_calls:
                    reply = model_reply.text.strip() or "The model returned an empty reply."
                    emit("reply", "Final reply", reply)
                    break

                assistant_calls = []
                for call in model_reply.tool_calls:
                    assistant_calls.append(
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": model_reply.text or None,
                        "tool_calls": assistant_calls,
                    }
                )

                for call in model_reply.tool_calls:
                    tool_call_count += 1
                    emit("tool", f"Tool call · {call.name}", call.arguments)
                    arguments_json = json.dumps(
                        call.arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                    previous = tool_results_by_call_id.get(call.id)
                    if previous is not None:
                        previous_name, previous_arguments, output = previous
                        if (previous_name, previous_arguments) != (call.name, arguments_json):
                            raise RuntimeError(
                                f"tool call id {call.id!r} was reused with different input"
                            )
                        emit(
                            "deduplicate",
                            f"Reused result · {call.name}",
                            {"tool_call_id": call.id},
                        )
                    else:
                        output = self.tools.execute(call.name, call.arguments)
                        tool_results_by_call_id[call.id] = (
                            call.name,
                            arguments_json,
                            output,
                        )
                    emit("observe", f"Observe · {call.name}", json.loads(output))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": output,
                        }
                    )
            else:
                reply = "I reached the iteration limit before completing the task."
                emit("guardrail", "Iteration limit reached", {"limit": self.max_iterations})
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            emit("error", "Turn failed", {"error": error})
            turn_id = self.memory.record_turn(
                user_message=user_message,
                reply="",
                mode=self.mode,
                iterations=iterations,
                trace=trace,
                status="failed",
                error=error,
            )
            raise AgentTurnError(
                error,
                trace=trace,
                iterations=iterations,
                tool_calls=tool_call_count,
                mode=self.mode,
                model=self.model.name,
                turn_id=turn_id,
            ) from exc

        emit(
            "done",
            "Turn persisted",
            {"iterations": iterations, "tool_calls": tool_call_count},
        )
        turn_id = self.memory.record_turn(
            user_message=user_message,
            reply=reply,
            mode=self.mode,
            iterations=iterations,
            trace=trace,
        )
        return AgentTurn(
            reply=reply,
            trace=trace,
            iterations=iterations,
            tool_calls=tool_call_count,
            mode=self.mode,
            model=self.model.name,
            turn_id=turn_id,
        )
