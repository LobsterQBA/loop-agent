const state = {
  mode: "demo",
  liveConfigured: false,
  turn: null,
  recorded: document.body.dataset.preview === "recorded",
  examples: [],
};

const form = document.querySelector("#agent-form");
const input = document.querySelector("#task-input");
const runButton = document.querySelector("#run-button");
const replyText = document.querySelector("#reply-text");
const traceList = document.querySelector("#trace-list");
const traceClock = document.querySelector("#trace-clock");
const modeNote = document.querySelector("#mode-note");

function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  return JSON.stringify(detail, null, 2);
}

function traceStep(event) {
  const article = document.createElement("article");
  article.className = "trace-step";
  article.dataset.kind = event.kind;

  const dot = document.createElement("span");
  dot.className = "trace-dot";
  dot.textContent = String(event.step).padStart(2, "0");

  const body = document.createElement("div");
  body.className = "trace-body";
  const title = document.createElement("h3");
  title.textContent = event.title;
  const explanations = {
    input: "The instruction starts a new turn with fresh working context.",
    reason:
      "The planner or model receives the instruction and any tool results so far.",
    tool: "The requested function receives these arguments. A request alone does not mean success.",
    deduplicate:
      "This tool call ID was already executed with the same input, so the loop reused its recorded result instead of repeating the side effect.",
    observe: event.detail?.ok
      ? "The tool returned successfully. This result goes back into working context."
      : "The tool reported an error. Inspect it before trusting a result or saving a value.",
    reply: "The planner or model returned text, so the loop stops.",
    guardrail:
      "The loop reached its iteration budget and stopped without completing the task.",
    done: "This completed turn and its trace are stored in the local SQLite database.",
  };
  const explanation = document.createElement("p");
  explanation.className = "step-explanation";
  explanation.textContent =
    explanations[event.kind] || "Inspect the recorded event below.";
  const disclosure = document.createElement("details");
  disclosure.open = event.kind === "observe";
  const summary = document.createElement("summary");
  summary.textContent = "Inspect recorded data";
  const detail = document.createElement("pre");
  detail.textContent = formatDetail(event.detail);
  disclosure.append(summary, detail);
  body.append(title, explanation, disclosure);

  const timing = document.createElement("span");
  timing.className = "trace-time";
  timing.textContent = `${event.elapsed_ms} ms`;
  article.append(dot, body, timing);
  return article;
}

function renderTrace(trace) {
  traceList.replaceChildren();
  trace.forEach((event) => traceList.append(traceStep(event)));
  traceList.scrollTop = 0;
  const last = trace.at(-1);
  traceClock.textContent = `${last?.elapsed_ms || 0} ms`;
}

function renderMemory(payload) {
  document.querySelector("#metric-memories").textContent =
    payload.memories.length;
  document.querySelector("#metric-turns").textContent = payload.turns.length;
  const grid = document.querySelector("#memory-grid");
  grid.replaceChildren();
  if (!payload.memories.length) {
    const empty = document.createElement("article");
    empty.className = "memory-empty";
    const label = document.createElement("span");
    label.textContent = "EMPTY BY DEFAULT";
    const text = document.createElement("p");
    text.textContent =
      "Ask the agent to remember something. It will appear here and remain after restart.";
    empty.append(label, text);
    grid.append(empty);
    return;
  }
  payload.memories.forEach((memory, index) => {
    const card = document.createElement("article");
    card.className = "memory-card";
    const label = document.createElement("span");
    label.textContent = `MEMORY / ${String(index + 1).padStart(2, "0")}`;
    const key = document.createElement("h3");
    key.textContent = memory.key;
    const value = document.createElement("p");
    value.textContent = memory.value;
    card.append(label, key, value);
    grid.append(card);
  });
}

async function refreshMemory() {
  const response = await fetch("/api/memory");
  if (!response.ok) throw new Error("Memory display could not refresh.");
  renderMemory(await response.json());
}

function setMode(mode) {
  if (mode === "live" && !state.liveConfigured) return;
  state.mode = mode;
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.classList.toggle("selected", button.dataset.mode === mode);
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  });
  modeNote.textContent =
    mode === "demo"
      ? "Deterministic planner · no API key"
      : "Function-calling model · key stays server-side";
}

document.querySelectorAll(".mode-button").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.example;
    if (!state.recorded) input.focus();
    document.querySelectorAll("[data-example]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    if (state.recorded && !runButton.disabled) form.requestSubmit();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  runButton.disabled = true;
  runButton.querySelector("span").textContent = "Running the loop…";
  replyText.textContent = "Running tools and collecting results…";
  state.turn = null;
  document.querySelector("#download-trace").disabled = true;
  document.querySelector("#turn-summary").textContent =
    "Waiting for this turn to complete…";
  traceList.replaceChildren();
  traceClock.textContent = "running";

  try {
    let payload;
    if (state.recorded) {
      const example = state.examples.find((item) => item.message === message);
      if (!example) throw new Error("Select one of the recorded examples.");
      payload = example.turn;
      renderMemory(example.memory);
    } else {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, mode: state.mode }),
      });
      payload = await response.json();
      if (!response.ok)
        throw new Error(payload.error || "The agent turn failed.");
    }
    state.turn = payload;
    replyText.textContent = payload.reply;
    renderTrace(payload.trace);
    document.querySelector("#turn-summary").textContent =
      `${state.recorded ? "Recorded turn" : "Turn"} ${payload.turn_id} · ${payload.mode} / ${payload.model} · ` +
      `${payload.iterations} planner/model calls · ${payload.tool_calls} tool call${payload.tool_calls === 1 ? "" : "s"}`;
    document.querySelector("#download-trace").disabled = false;
    try {
      if (!state.recorded) await refreshMemory();
    } catch {
      document.querySelector("#turn-summary").textContent +=
        " · Memory display could not refresh.";
    }
  } catch (error) {
    replyText.textContent = error.message;
    traceClock.textContent = "error";
    document.querySelector("#turn-summary").textContent =
      "No completed trace returned for this request.";
  } finally {
    runButton.disabled = false;
    runButton.querySelector("span").textContent = state.recorded
      ? "Show recorded turn"
      : "Run one turn";
  }
});

document.querySelector("#download-trace").addEventListener("click", () => {
  if (!state.turn) return;
  const blob = new Blob([JSON.stringify(state.turn, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `loop-agent-turn-${state.turn.turn_id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

async function boot() {
  setMode("demo");
  if (state.recorded) {
    runButton.disabled = true;
    try {
      const response = await fetch("./examples.json");
      if (!response.ok)
        throw new Error(
          "Could not load the recorded examples. Reload to retry.",
        );
      const recording = await response.json();
      state.examples = recording.examples;
      input.value = state.examples[0].message;
      input.readOnly = true;
      modeNote.textContent =
        "Recorded Python run · no model call in this browser";
      runButton.querySelector("span").textContent = "Show recorded turn";
      document.querySelector("#system-status").textContent =
        "recorded walkthrough";
      document.querySelector("#recording-source").textContent =
        `Generated from commit ${recording.commit.slice(0, 7)}. Each turn ran in a fresh Python process.`;
      runButton.disabled = false;
      document
        .querySelector("[data-example]")
        .setAttribute("aria-pressed", "true");
      form.requestSubmit();
    } catch (error) {
      replyText.textContent = error.message;
    }
    return;
  }
  try {
    const response = await fetch("/api/status");
    const status = await response.json();
    state.liveConfigured = Boolean(status.live_configured);
    const liveButton = document.querySelector('[data-mode="live"]');
    liveButton.disabled = !state.liveConfigured;
    liveButton.title = state.liveConfigured
      ? "Use the configured live model"
      : "Add AGENT_API_KEY and AGENT_MODEL to .env";
    const systemStatus = document.querySelector("#system-status");
    systemStatus.classList.add("ready");
    systemStatus.innerHTML = "<i></i> local · ready";
    await refreshMemory();
  } catch (error) {
    document.querySelector("#system-status").textContent = "offline";
    replyText.textContent = "Start the local Python server to use the cockpit.";
  }
}

boot();
