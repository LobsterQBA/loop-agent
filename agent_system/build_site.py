"""Build a static, explicitly recorded walkthrough from real demo executions."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_system.walkthrough import run_turn

MESSAGES = [
    "Calculate 17 * 23 and remember the result as launch score.",
    "What do you remember about launch score?",
    "Calculate 1 / 0 and remember the result as invalid score.",
]


def build_site(destination: Path) -> None:
    source = Path(__file__).parent / "static"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "style.css"):
        shutil.copyfile(source / name, destination / name)
    html = (source / "index.html").read_text()
    html = html.replace('<body>', '<body data-preview="recorded">')
    html = html.replace('href="/style.css"', 'href="./style.css"')
    html = html.replace('src="/app.js"', 'src="./app.js"')
    start = html.index('      <section class="guide"')
    end = html.index('      <section class="workbench"', start)
    html = html[:start] + '''      <section class="guide" aria-labelledby="guide-title">
        <p><strong>Recorded walkthrough.</strong> These are real Python runs, recorded at build time;
          it does not run an AI model or save your data. Select an example below.</p>
        <nav class="project-links" aria-label="Explore the project">
          <a href="https://github.com/LobsterQBA/loop-agent#try-it-locally">Run it locally ↗</a>
          <a href="https://github.com/LobsterQBA/loop-agent/blob/main/docs/architecture.md">Read the design ↗</a>
        </nav>
        <span id="guide-title" hidden>Three recorded examples</span>
      </section>

''' + html[end:]
    html = html.replace('<footer>', '<footer><p id="recording-source"></p>')
    html = html.replace('<section class="workbench"', '<section id="demo" class="workbench"')
    html = html.replace('Give the agent a job', 'Choose a recorded task')
    html = html.replace('''            <div class="mode-control" aria-label="Agent mode">''',
                        '''            <div class="mode-control" aria-label="Agent mode" hidden>''')
    for label, replacement in (
        ("recall memory", "2. recall after restart"),
        ("calculate + remember", "1. calculate + remember"),
        ("try a failure", "3. try a failure"),
    ):
        html = re.sub(r">\s*" + re.escape(label) + r"\s*</button>",
                      f">{replacement}</button>", html)
    html = html.replace('>Instruction</label>', '>Recorded instruction</label>')
    html = html.replace('Recorded calls and results, shown after the turn completes.',
                        'Recorded calls and results from the selected example.')
    html = html.replace('Saved facts', 'Saved facts after this example')
    html = html.replace('Waiting for a task. The trace will reveal every step.',
                        'Choose an example, then show its recorded turn. Expand each step to check the data.')
    html = html.replace('Run a task, then expand each step to inspect its recorded data.',
                        'Choose an example to inspect its recorded calls and results.')
    html = html.replace('Ask the agent to remember something. It will appear here and remain after restart.',
                        'Show a recorded turn to see its SQLite snapshot. This page does not store visitor data.')
    (destination / "index.html").write_text(html)
    (destination / ".nojekyll").touch()
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "local build"
    examples = []
    turns = []
    with TemporaryDirectory(prefix="loop-agent-site-") as folder:
        database = Path(folder) / "state.db"
        for message in MESSAGES:
            result = run_turn(database, message)
            turns.append({"id": result["turn"]["turn_id"]})
            examples.append({
                "message": message,
                "turn": result["turn"],
                "memory": {"memories": result["memories"], "turns": list(turns)},
            })
    (destination / "examples.json").write_text(
        json.dumps({"commit": commit, "examples": examples}, ensure_ascii=False, indent=2)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()
    build_site(args.output)
    print(f"Recorded walkthrough built at {args.output}")


if __name__ == "__main__":
    main()
