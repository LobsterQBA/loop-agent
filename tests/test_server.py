import json
import threading
import urllib.error
import urllib.request

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


def test_local_api_runs_a_demo_turn(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, system = request_json(f"{base}/api/status")
        assert status == 200
        assert system["tools"] == ["calculate", "current_time", "remember", "recall"]

        status, turn = request_json(
            f"{base}/api/run",
            payload={"message": "Calculate 8 * 9", "mode": "demo"},
        )
        assert status == 200
        assert turn["tool_calls"] == 1
        assert "72" in turn["reply"]
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


def test_run_rejects_empty_non_string_and_oversized_messages(tmp_path):
    server = create_server(port=0, home=tmp_path / "agent-home")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for message, expected in [
            ("   ", "message must not be empty"),
            (["not", "a", "string"], "message must be a string"),
            ("x" * 4_001, "message must be at most 4000 characters"),
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
