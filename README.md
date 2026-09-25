# Loop Agent

A small Python app that shows how an agent uses tools to finish a task.

Ask it to **calculate 17 × 23 and save the result**. It runs the calculator, stores `391`
in SQLite, and shows each tool call and result. Restart the app and ask for the value again:
it is still there.

I built this to understand the loop behind a tool-using agent: choose an action, run it,
read the result, and decide what to do next. The core loop is in
[agent.py](agent_system/agent.py).

**[Try the browser demo →](https://lobsterqba.github.io/loop-agent/)**

The browser demo replays three recorded runs: calculate and save, recall after a restart,
and handle a failed calculation. Run locally to enter your own tasks.

[![CI](https://github.com/LobsterQBA/loop-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/LobsterQBA/loop-agent/actions/workflows/ci.yml)

[![Loop Agent showing a task, its result, and the steps it took](docs/cockpit.png)](https://lobsterqba.github.io/loop-agent/)

## The loop at a glance

```mermaid
flowchart LR
    Task["Your task"] --> Planner{"Choose the next step"}
    Planner -->|Call a tool| Tool["Calculate, save, recall, or get time"]
    Tool --> Result["Tool result"]
    Result --> Planner
    Planner -->|Task finished| Reply["Reply"]
    Reply --> Record["Save the run and show its steps"]
```

The planner uses fixed rules in Demo mode or a model in Live mode. The loop stops after
six planner calls by default if it has not finished, and a separate 12-call tool budget
prevents one model response from bypassing that limit with an oversized batch. Each tool
call's serialized arguments are capped at 8 KiB before any tool in the batch executes. Tool
schemas also reject missing, extra, incorrectly typed, or out-of-range string arguments before
execution. Tool results above 16 KiB are replaced with a bounded error and SHA-256 fingerprint
before they enter the next model context or persisted trace.

## Three examples

```mermaid
flowchart TB
    subgraph Save["1 · Calculate and save"]
        direction LR
        A["17 × 23"] --> B["Calculator: 391"] --> C[("Save launch score = 391")]
    end
    subgraph Recall["2 · Recall after restarting Python"]
        direction LR
        D["Ask for launch score"] --> E[("Read the same SQLite file")] --> F["Return 391"]
    end
    subgraph Fail["3 · Handle a failed calculation"]
        direction LR
        G["1 ÷ 0"] --> H["Calculator: error"] --> I["Explain the error; skip saving"]
    end
    Save ~~~ Recall ~~~ Fail
```

These are the fixed-rule demo paths. The browser demo lets you open the recorded calls
and results for all three. Live mode makes its own tool choices.

## Try it locally

Requires **Python 3.11+**. The default demo needs no extra packages or API key.

```bash
git clone https://github.com/LobsterQBA/loop-agent.git
cd loop-agent
python3 -m agent_system
```

Open [localhost:8787](http://127.0.0.1:8787) and try the three examples:

1. **Calculate + remember:** run the prefilled task. The answer is `391`. Expand the steps
   to see the calculation and the saved value.
2. **Recall memory:** stop the server with Ctrl+C, restart it from the same directory,
   and run the recall example. It retrieves `launch score: 391` from SQLite.
3. **Try a failure:** division by zero returns an error without saving an invalid result.

Demo mode follows a few fixed rules. Live mode connects an LLM to the same tools.
The [walkthrough](docs/walkthrough.md) explains each step and includes troubleshooting.

## Where to find the code

| Part | What it does |
| --- | --- |
| [Agent loop](agent_system/agent.py) | Runs the steps, enforces planner, tool-call, argument-size, and output-size budgets, rejects ambiguous duplicate IDs within one model response, and safely reuses matching results across later iterations |
| [Trace evaluation](agent_system/evaluation.py) | Runs deterministic integrity checks over the recorded steps, timing, tool observations and their non-empty call identities, terminal event, and outcome |
| [Tools](agent_system/tools.py) | Validate declared argument shapes and string-length bounds, then calculate, remember a fact, recall saved facts, or get the current time |
| [Memory](agent_system/memory.py) | Stores facts and run history, including model provenance, in a local SQLite database |
| [Model adapters](agent_system/models.py) | Use fixed demo rules or an OpenAI-compatible model |
| [Web interface](agent_system/static/index.html) | Shows the task, reply, saved facts, and expandable execution steps |

Each task starts with fresh working messages; saved facts are available through the recall tool.
The execution record shows tool calls and results after a run finishes, not private model reasoning.
Persisted runs retain the planner/model name, so reopened evidence still identifies what produced it.
Each returned run also reports whether its trace passed seven deterministic integrity checks,
including whether its lifecycle status is valid and its declared iteration and tool-call counts
match the events. This evaluates the evidence structure, not whether the model's answer was correct
or useful.
If a provider or loop error aborts a run, the cockpit still shows and exports the persisted failed
trace, including any earlier tool effects. The recent-run cards reopen completed and failed traces
after a browser refresh or server restart.

## Connect a model

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[live]'
cp .env.example .env
```

Set `AGENT_API_KEY` and `AGENT_MODEL` in `.env`, then start `python3 -m agent_system`
and select **Live**. Set `AGENT_BASE_URL` if using another OpenAI-compatible endpoint.
On Windows, activate the environment with `.venv\Scripts\activate`.

The key stays on the server. Tasks and tool results go to your configured provider, whose
usage fees apply. The included tests use demo rules; live-model behavior depends on the provider and model.

## Run the checks

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
ruff check .
python -m agent_system.walkthrough
```

The walkthrough checks calculation, saving, recall in a fresh process, and a failed calculation.
The tests also cover loop, tool-call, argument-size, and tool-output budgets, tool-schema validation
including declared string limits,
duplicate IDs and retried tool calls, matching tool-call/observation identities, failure records,
reopening saved traces, and HTTP input validation.

## Limits and further reading

This is a local learning project with four tools. The server binds to localhost and has no
login or multi-user support. Memory writes commit separately from the run record, so a failed
run can leave earlier writes in place. Demo prompts are limited to the supplied patterns.

- [Step-by-step walkthrough](docs/walkthrough.md)
- [Architecture, API, and limitations](docs/architecture.md)
- [Building and hosting the browser demo](docs/hosting.md)

Built by [Leo Zhao](https://github.com/LobsterQBA). Inspired by
[Waku](https://github.com/ShenSeanChen/waku-agent), implemented from scratch. [MIT license](LICENSE).
