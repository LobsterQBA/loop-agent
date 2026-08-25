"""Tiny local HTTP server for the Agent System Mini cockpit."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agent_system.agent import AgentSystem
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel, LiveModel
from agent_system.tools import build_tools

STATIC_ROOT = Path(__file__).parent / "static"
MAX_BODY_BYTES = 16_384
MAX_MESSAGE_CHARS = 4_000


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load a minimal KEY=VALUE file without adding a runtime dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class Application:
    def __init__(self, home: Path | None = None):
        load_dotenv()
        self.home = home or Path(os.getenv("AGENT_HOME", ".agent-mini"))
        self.memory = MemoryStore(self.home / "state.db")
        self.tools = build_tools(self.memory)
        self.demo = AgentSystem(
            model=DemoModel(), tools=self.tools, memory=self.memory, mode="demo"
        )
        self._live: AgentSystem | None = None
        self._live_lock = threading.Lock()

    @property
    def live_configured(self) -> bool:
        return bool(os.getenv("AGENT_API_KEY") and os.getenv("AGENT_MODEL"))

    def live(self) -> AgentSystem:
        if not self.live_configured:
            raise RuntimeError("Live mode needs AGENT_API_KEY and AGENT_MODEL in .env")
        with self._live_lock:
            if self._live is None:
                model = LiveModel(
                    api_key=os.environ["AGENT_API_KEY"],
                    model=os.environ["AGENT_MODEL"],
                    base_url=os.getenv("AGENT_BASE_URL") or None,
                )
                self._live = AgentSystem(
                    model=model, tools=self.tools, memory=self.memory, mode="live"
                )
        return self._live

    def run(self, message: str, mode: str) -> dict:
        if mode not in {"demo", "live"}:
            raise ValueError("mode must be demo or live")
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message must be at most {MAX_MESSAGE_CHARS} characters")
        agent = self.demo if mode == "demo" else self.live()
        return agent.run(message).to_dict()

    def status(self) -> dict:
        return {
            "name": "Agent System Mini",
            "version": "0.1.0",
            "live_configured": self.live_configured,
            "database": str(self.memory.path),
            "tools": self.tools.names(),
        }


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "AgentSystemMini/0.1"

    @property
    def app(self) -> Application:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        print(f"[agent-mini] {self.address_string()} · {format % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:",
        )

    def _json(self, payload: dict | list, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid request size")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(self.app.status())
            return
        if path == "/api/memory":
            self._json(
                {
                    "memories": self.app.memory.recall(limit=20),
                    "turns": self.app.memory.recent_turns(limit=8),
                }
            )
            return

        static_path = "/index.html" if path == "/" else path
        candidate = (STATIC_ROOT / static_path.lstrip("/")).resolve()
        if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            message = payload.get("message", "")
            if not isinstance(message, str):
                raise TypeError("message must be a string")
            mode = str(payload.get("mode", "demo"))
            self._json(self.app.run(message, mode))
        except (TypeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except Exception as exc:  # noqa: BLE001 - keep the local HTTP process alive
            self._json(
                {"error": f"Agent turn failed: {type(exc).__name__}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


class AgentServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], app: Application):
        super().__init__(address, AgentHandler)
        self.app = app


def create_server(*, host: str = "127.0.0.1", port: int = 8787, home: Path | None = None):
    return AgentServer((host, port), Application(home=home))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agent System Mini cockpit")
    parser.add_argument("--port", type=int, default=int(os.getenv("AGENT_PORT", "8787")))
    parser.add_argument("--open", action="store_true", help="Open the cockpit in your browser")
    args = parser.parse_args()
    server = create_server(port=args.port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Agent System Mini is running at {url}")
    print("Demo mode needs no API key. Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent System Mini.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
