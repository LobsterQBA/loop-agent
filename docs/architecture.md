# Architecture: make the work checkable

[← Project overview](../README.md) · [Step-by-step walkthrough](walkthrough.md)

The core design separates **intent**, **execution**, and **evidence**. The planner requests a tool;
the registry executes it; the observation records what happened. A final answer is one output of that
process, not sufficient evidence that a requested action succeeded.

## Source reading order

| File | Responsibility | Question to ask while reading |
| --- | --- | --- |
| [agent.py](../agent_system/agent.py) | One bounded turn | When does the loop continue, stop, and persist? |
| [models.py](../agent_system/models.py) | Demo and live adapters | What changes when fixed rules are replaced by an LLM? |
| [tools.py](../agent_system/tools.py) | Registry, schemas, execution | What can actually run, and how do errors return? |
| [memory.py](../agent_system/memory.py) | SQLite facts and turn records | Which state outlives the process? |
| [server.py](../agent_system/server.py) | HTTP validation and static assets | Where does external input enter? |
| [app.js](../agent_system/static/app.js) | Explanations and raw event disclosures | Can a reader distinguish a request from a successful result? |

## Lifecycle of one turn

```mermaid
sequenceDiagram
    participant UI as Local UI
    participant Loop as AgentSystem
    participant Model as Planner / LLM
    participant Tools as Registry
    participant DB as SQLite
    UI->>Loop: Validated instruction
    loop At most 6 iterations by default
        Loop->>Model: Working messages + tool schemas
        alt Tool calls returned
            Model-->>Loop: Names + arguments
            Loop->>Tools: Execute registered function
            opt remember or recall
                Tools->>DB: Write or query facts
                DB-->>Tools: Result
            end
            Tools-->>Loop: Structured success or error
            Note over Loop: Append observation to working messages
        else Text returned
            Model-->>Loop: Final reply
            Note over Loop: Exit loop
        end
    end
    Loop->>DB: Save turn + trace
    Loop-->>UI: Reply + trace + counts
```

The loop uses the same `Model.complete(messages, tools)` interface for both modes.
`DemoModel` recognizes a few patterns; it does not simulate LLM quality. `LiveModel` calls an
OpenAI-compatible chat-completions endpoint with function schemas. No model SDK is needed for demo mode.

An iteration is a model/planner call, not a tool call. Multiple tools returned in one iteration execute
sequentially. Text without tool calls ends the turn. Exhaustion returns a guardrail reply and saves its trace.
The default is six iterations; the constructor clamps overrides to 1–12.

## What is stored, and what is not

| State | Lifetime | Detail |
| --- | --- | --- |
| Working messages | One turn | System instruction, user input, tool requests, and observations |
| Facts | Durable | Unique key; later writes replace its value; text normalized and length-limited |
| Turn ledger | Durable after completion | User input, reply, mode, iterations, timestamp, JSON trace |
| UI trace | Current completed turn | Expand raw data or export returned JSON; not streamed |
| Live API key | Server configuration | Not sent to the browser or stored in the turn ledger |

Facts and the ledger live in `.agent-mini/state.db` by default. Recall uses literal substring matching
with escaped SQL wildcard characters and parameterized values. It is not vector retrieval.
The memory endpoint returns capped recent lists. The UI labels these as recent counts.
Old traces remain in SQLite, but browsing them in the UI is not yet implemented.

A `reason` event means “a model call is starting”; this legacy event name does not imply access to
private reasoning. A `done` event is assembled before the database write and returned only after that
write succeeds; its elapsed time does not measure the commit duration.

## Tradeoffs and next decisions

| Choice | Benefit | Cost / when to revisit |
| --- | --- | --- |
| Plain Python loop, no agent framework | Control flow fits in one file and is easy to inspect | More orchestration, retries, and cancellation would need explicit implementation |
| Keyless deterministic demo | Reproducible onboarding and regression checks | Limited language patterns; says nothing about live-model task success |
| SQLite instead of a service | No infrastructure setup; restart persistence is easy to verify | No multi-user isolation; concurrent writes and growth need more design |
| Explicit remember/recall tools | Clear distinction between working context and durable facts | Models may choose the wrong facts; no semantic retrieval or conflict resolution |
| Four local tools | Small, inspectable action surface | Narrow task usefulness; adding external writes would require permission and recovery policies |
| Completed-turn trace | Simple API and a stable inspection artifact | No progress streaming; model or persistence failure can leave no saved trace |

The next priority is **durable failure records with explicit turn status**. Today, memory writes commit
independently of the final trace. A later error or process crash can leave a saved fact without a turn
record. A production design would need a policy for partial effects, tool-call budgets, timeouts,
retries, and cancellation before adding more tools.

After that, evaluate live mode with task-specific assertions (correct arithmetic, evidence-backed
memory writes, correct recall, bounded failure handling). Pin the model and configuration and report
success and failure counts. Deterministic tests are not an LLM benchmark.

## Boundaries worth reviewing

- HTTP input must be JSON, with a nonempty message of at most 2,000 characters. The request body is capped at 16,384 bytes.
- The calculator allows a restricted AST and rejects calls, names, complex results, nonfinite results,
  and results beyond its numeric bound. This is not a general code sandbox or CPU budget.
- Registered tool exceptions become `{ok: false, error: ...}` observations. Schemas describe inputs
  to the model; this registry does not implement full JSON Schema validation.
- In demo mode, a failed calculation prevents a follow-on result write. The live model is instructed
  to inspect results, but there is no equivalent general write-policy enforcement.
- The server binds to `127.0.0.1`. It has no authentication, tenant isolation, or deployment hardening.
- Live mode sends working messages, schemas, and tool results to the configured provider. Locally
  stored instructions and facts are plain text in SQLite, not encrypted by this app.

## Verification map

| Behavior | Evidence |
| --- | --- |
| Calculation feeds the next memory write | `test_demo_agent_chains_calculate_and_remember` |
| Persistence survives fresh Python processes | `python -m agent_system.walkthrough` |
| Failed calculation is not saved; prior value survives | Failure regression tests in [test_agent.py](../tests/test_agent.py) |
| Endless tool requests stop | `test_iteration_guardrail_stops_endless_tool_calls` |
| Restricted arithmetic and tool errors | [test_tools.py](../tests/test_tools.py) |
| Input validation and local API | [test_server.py](../tests/test_server.py) |

CI runs on Python 3.11 and 3.12. Browser layout, accessibility, provider compatibility, model quality,
and production load require separate validation; a green Python suite does not establish them.
