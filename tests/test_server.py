import json
import threading
import urllib.error
import urllib.request
from importlib.metadata import version

from agent_system.server import create_server


def request_json(url, *, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.load(response)


class FailingModel:
    name = "failing-test-model"

    def complete(self, messages, tools):
        raise RuntimeError("provider disconnected")


def test_local_api_runs_a_demo_turn(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, system = request_json(f"{base}/api/status")
        assert status == 200
        assert system["version"] == version("loop-agent")
        assert system["tools"] == ["calculate", "current_time", "remember", "recall"]
        assert system["limits"] == {
            "max_message_chars": 2_000,
            "max_iterations": 6,
            "max_tool_calls": 12,
            "max_tool_argument_bytes": 8_192,
            "max_tool_output_bytes": 16_384,
        }

        status, turn = request_json(
            f"{base}/api/run",
            payload={"message": "Calculate 8 * 9", "mode": "demo"},
        )
        assert status == 200
        assert turn["tool_calls"] == 1
        assert "72" in turn["reply"]
        assert turn["evaluation"]["trace_integrity"] == "passed"
        assert turn["evaluation"]["summary"]["tool_calls"] == 1

        status, saved_turn = request_json(f"{base}/api/turns/{turn['turn_id']}")
        assert status == 200
        assert saved_turn["turn_id"] == turn["turn_id"]
        assert saved_turn["reply"] == turn["reply"]
        assert saved_turn["model"] == turn["model"] == "demo-planner"
        assert saved_turn["trace"] == turn["trace"]
        assert saved_turn["tool_calls"] == 1
        assert saved_turn["evaluation"]["trace_integrity"] == "passed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_saved_turn_api_returns_not_found_for_unknown_or_invalid_id(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path in ["/api/turns/999", "/api/turns/not-an-id"]:
            try:
                request_json(f"{base}{path}")
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
                assert json.loads(exc.read()) == {"error": "turn not found"}
            else:
                raise AssertionError("unknown turn should return HTTP 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_live_mode_requires_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            request_json(
                f"{base}/api/run",
                payload={"message": "hello", "mode": "live"},
            )
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
            payload = json.loads(exc.read())
            assert "AGENT_API_KEY" in payload["error"]
        else:
            raise AssertionError("live mode should be unavailable without configuration")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_failed_agent_turn_returns_its_persisted_trace(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    server.app.demo.model = FailingModel()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            request_json(f"{base}/api/run", payload={"message": "start", "mode": "demo"})
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            payload = json.loads(exc.read())
            assert payload["status"] == "failed"
            assert payload["error"] == "RuntimeError: provider disconnected"
            assert payload["model"] == "failing-test-model"
            assert [event["kind"] for event in payload["trace"]] == [
                "input",
                "reason",
                "error",
            ]
            assert server.app.memory.recent_turns()[0]["id"] == payload["turn_id"]
            assert server.app.memory.recent_turns()[0]["model"] == "failing-test-model"
        else:
            raise AssertionError("failed agent turn should return HTTP 500")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_run_rejects_empty_non_string_and_oversized_messages(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for message, expected in [
            ("   ", "message must not be empty"),
            (["not", "a", "string"], "message must be a string"),
            ("x" * 2_001, "message must be at most 2000 characters"),
        ]:
            try:
                request_json(
                    f"{base}/api/run",
                    payload={"message": message, "mode": "demo"},
                )
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
                assert expected in json.loads(exc.read())["error"]
            else:
                raise AssertionError("invalid message should return HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_run_requires_json_content_type(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    request = urllib.request.Request(
        f"{base}/api/run",
        data=json.dumps({"message": "hello"}).encode(),
        headers={"Content-Type": "text/plain"},
    )
    try:
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 415
            assert json.loads(exc.read()) == {
                "error": "Content-Type must be application/json"
            }
        else:
            raise AssertionError("non-JSON content type should return HTTP 415")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_run_rejects_invalid_content_length_without_leaking_parser_error(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    request = urllib.request.Request(
        f"{base}/api/run",
        data=json.dumps({"message": "hello"}).encode(),
        headers={
            "Content-Type": "application/json",
            "Content-Length": "not-a-number",
        },
    )
    try:
        try:
            urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert json.loads(exc.read()) == {"error": "invalid request size"}
        else:
            raise AssertionError("invalid Content-Length should return HTTP 400")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
