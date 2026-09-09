# Presenting Loop Agent

[← Project overview](../README.md)

Use these descriptions only after you can run the example and explain the linked implementation.
They describe the project as built; they make no claims about users, commercial impact, or measured
LLM performance.

## Resume

**Loop Agent — Python, SQLite, tool calling, execution tracing**

- Built an inspectable Python agent loop with four local tools, SQLite-backed memory, and expandable execution traces; added a keyless demo and an optional function-calling LLM adapter.
- Added regression checks for failed-result persistence and a reproducible walkthrough that verifies memory across fresh Python processes.

## A short explanation

“Loop Agent is a small project about checking an agent's work. You can ask it to calculate a value and
remember it, inspect the tool calls and results, and restart the app to verify the memory survives.
The main design choice is to separate an action request from evidence that it succeeded. The default
demo is deterministic so anyone can reproduce it; a live model can use the same loop and tools.”

## Questions to prepare for

| Question | A concrete answer to understand |
| --- | --- |
| Why not just show the final answer? | A claim that something was saved is weaker than a successful write observation and a fresh-process recall. |
| Is the no-key demo an LLM? | No. It is a rule-based planner exercising the real loop and tools. The live adapter is separate. |
| What did the failure case expose? | The planner used to save a calculator error as a value. It now stops the dependent write, with tests for empty and preexisting memory. |
| Why SQLite? | It makes persistence easy to run and inspect without infrastructure. It does not solve multi-user isolation or distributed writes. |
| What would you build next? | Durable failure records and explicit turn status, because tool effects can commit before a turn record does. |
| What do the tests prove? | Deterministic control flow, tool behavior, validation, and persistence. They do not prove live-model reliability. |

For deeper answers, follow the [source reading order](architecture.md#source-reading-order).
