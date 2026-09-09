# Follow one task, all the way through

[← Project overview](../README.md) · [Architecture](architecture.md)

**Task:** Calculate 17 × 23 and remember the result as launch score.

The expected outcome is a saved fact: `launch score = 391`. The useful part is the chain of evidence:
calculation requested → result observed → memory written → value retrieved in a fresh process.
The values below describe the deterministic demo. Timings and IDs vary between runs.

## Read without installing anything

<details>
<summary><strong>1. Start the turn — what context does the agent have?</strong></summary>

The server validates the instruction. The loop starts with a system instruction and this user message.
Previous chat messages are not loaded. Saved facts are accessible through the recall tool.
The trace begins with `input` and then a model-call event.

[Source: AgentSystem.run](../agent_system/agent.py)

</details>

<details>
<summary><strong>2. Request a calculation — a request is not a result</strong></summary>

The demo planner recognizes arithmetic and asks for `calculate`:

```json
{"expression": "17 * 23"}
```

The registry looks up that name. The calculator parses a restricted arithmetic syntax tree;
it cannot run Python functions, imports, or attribute access.

[Source: DemoModel.complete](../agent_system/models.py) · [Source: safe_calculate](../agent_system/tools.py)

</details>

<details>
<summary><strong>3. Observe 391 — what evidence returns to the planner?</strong></summary>

The tool returns:

```json
{"ok": true, "result": 391}
```

The loop records this observation and appends it to working messages. The planner is called again
with the result available. This is why a tool request and an observation are separate trace events.

[Source: AgentSystem.run](../agent_system/agent.py)

</details>

<details>
<summary><strong>4. Save the observed result — what actually persists?</strong></summary>

The second planner call requests `remember`:

```json
{"key": "launch score", "value": "391"}
```

SQLite stores the value as text. The observation confirms the write:

```json
{"ok": true, "result": {"saved": true, "key": "launch score", "value": "391"}}
```

Saving the same key updates it. This is an explicit fact store, not semantic search or conversation memory.

[Source: MemoryStore.remember](../agent_system/memory.py)

</details>

<details>
<summary><strong>5. Finish — why three planner calls but only two tool calls?</strong></summary>

The first planner call requests calculation, the second requests memory, and the third returns text.
The loop saves the turn and its trace. The UI shows a short explanation for each event; expand
**Inspect recorded data** for exact arguments and results. Download JSON to keep the complete returned turn.

The expected event order is:

```text
input → model call → tool → observation → model call → tool → observation
      → model call → reply → persisted
```

The API retains the event kind `reason` for compatibility, but its content identifies the model call,
not hidden reasoning. `elapsed_ms` is elapsed wall time since the turn began, not token usage or a benchmark.

[Source: trace rendering](../agent_system/static/app.js)

</details>

<details>
<summary><strong>6. Restart and recall — how do we rule out in-process memory?</strong></summary>

Stop and restart the Python server from the same directory. Ask:

> What do you remember about launch score?

The planner requests `recall` with `{"query": "launch score"}`. SQLite returns the stored key and value,
plus its update timestamp. This turn takes two planner calls and one tool call. A fresh process can
retrieve the fact even though its working messages are new.

The CLI walkthrough below verifies this by launching a separate Python process for each turn.

[Source: runnable walkthrough](../agent_system/walkthrough.py)

</details>

## Try the failure path

> Calculate 1 / 0 and remember the result as invalid score.

Expected: the calculator reports `ok: false`; the demo planner says it did not save a result.
There is one calculator call, no memory write, and a completed trace explaining the failure.
If the key already existed, this failed calculation leaves its previous value untouched.

This illustrates the project's central choice: a tool error should stay an error, rather than becoming
an apparently valid fact. This behavior is guaranteed by demo rules and regression tests; the optional
live model makes its own tool decisions and is not proven to follow the same policy.

## Run the checks without a browser

From the cloned repository, with Python 3.11+:

```bash
python3 -m agent_system.walkthrough
```

Expected output:

```text
PASS calculate + remember: 391; 3 planner calls; 2 tool calls
PASS restart + recall: launch score = 391 in a fresh process
PASS failed calculation: error observed; no memory written
PASS all checks; temporary state removed
```

The command uses temporary state and exits unsuccessfully if any check fails. It exercises the Python
core in separate processes; the HTTP layer is covered separately in `tests/test_server.py`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `python3` not found | Install Python 3.11+ or try `python --version` |
| `No module named agent_system` | Run from the repository root |
| Port already in use | Run `python3 -m agent_system --port 8788` and open localhost:8788 |
| Recall finds nothing | Use the same launch directory and `AGENT_HOME`; first run calculate + remember |
| Live is disabled | Set both model and API key in `.env`, install `.[live]`, then restart |
| Demo does not understand a prompt | Use the supplied examples; the demo is a small rule-based planner |

To experiment with fresh app state without deleting anything, set `AGENT_HOME` to another directory
before starting the server. Keep exported turns private if they contain personal instructions or facts.
