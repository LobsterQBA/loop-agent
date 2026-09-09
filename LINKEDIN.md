# Loop Agent — project description draft

Loop Agent is a small Python project for checking what happens inside an agent turn.

Ask it to calculate a value and remember it, expand the tool calls and observations, then restart
the app and retrieve the saved fact. The default demo needs no API key; an optional function-calling
model uses the same loop and tools.

The design centers on a simple distinction: requesting an action is not evidence that it succeeded.
One practical example is the failure path: a calculator error stays an error and is not saved as a result
in demo mode.

Python · SQLite · local tools · expandable execution traces

Repository: https://github.com/LobsterQBA/loop-agent

For resume wording and technical discussion prompts, see [Presenting Loop Agent](docs/presentation.md).
