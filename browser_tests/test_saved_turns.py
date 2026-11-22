import json
import sqlite3
import threading

import pytest
from playwright.sync_api import expect

from agent_system.server import create_server


@pytest.fixture
def saved_turns(tmp_path, page):
    server = create_server(port=0, home=tmp_path / "agent-home")
    with server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            turns = []
            for message in ("Calculate 8 * 9", "Calculate 6 * 7"):
                response = page.request.post(f"{base}/api/run", data={"message": message})
                assert response.ok, response.text()
                turns.append(response.json()["turn_id"])

            good_id, corrupt_id = turns
            with sqlite3.connect(server.app.memory.path) as db:
                db.execute("UPDATE turns SET trace_json = ? WHERE id = ?", ('[{"kind":', corrupt_id))

            good_response = page.request.get(f"{base}/api/turns/{good_id}")
            assert good_response.ok, good_response.text()
            yield base, good_response.json(), corrupt_id
        finally:
            server.shutdown()
            thread.join()


def test_corrupt_saved_turn_clears_trace_and_download_recovers(page, saved_turns):
    base, good_turn, corrupt_id = saved_turns
    good_id = good_turn["turn_id"]
    page.goto(base)
    good_card = page.locator(f'[data-turn-id="{good_id}"]')
    trace = page.locator("#trace-list .trace-step")
    download_button = page.get_by_role("button", name="Download turn JSON")
    summary = page.locator("#turn-summary")

    good_card.press("Enter", timeout=5000)
    expect(summary).to_contain_text(f"turn {good_id} ·")
    expect(trace).to_have_count(len(good_turn["trace"]))
    expect(download_button).to_be_enabled()

    page.locator(f'[data-turn-id="{corrupt_id}"]').press("Enter", timeout=5000)
    expect(page.locator("#reply-text")).to_have_text("Saved turn trace is corrupt.")
    expect(summary).to_have_text(f"Saved turn {corrupt_id} could not be loaded.")
    expect(trace).to_have_count(0)
    expect(page.locator("#trace-clock")).to_have_text("error")
    expect(download_button).to_be_disabled()

    good_card.press("Enter", timeout=5000)
    expect(summary).to_contain_text(f"turn {good_id} ·")
    expect(page.locator("#reply-text")).to_have_text(good_turn["reply"])
    expect(trace).to_have_count(len(good_turn["trace"]))
    with page.expect_download() as pending:
        download_button.press("Enter", timeout=5000)
    download = pending.value
    assert download.suggested_filename == f"loop-agent-turn-{good_id}.json"
    assert json.loads(download.path().read_text(encoding="utf-8")) == good_turn


def hold_saved_turn_request(page, base, earlier_id):
    earlier_url = f"{base}/api/turns/{earlier_id}"
    held_routes = []

    def hold_request(route):
        held_routes.append(route)

    page.route(earlier_url, hold_request)
    page.goto(base)
    # Wait until the click handler has had a chance to process the delayed JSON
    # before asserting that the current UI survived it.
    page.evaluate(
        """earlierUrl => {
            const fetch = window.fetch;
            window.fetch = async (...args) => {
                const response = await fetch(...args);
                if (response.url === earlierUrl) {
                    const json = response.json.bind(response);
                    response.json = async () => {
                        const body = await json();
                        setTimeout(() => { window.earlierHistoryResponseHandled = true; });
                        return body;
                    };
                }
                return response;
            };
        }""",
        earlier_url,
    )
    with page.expect_request(earlier_url):
        page.locator(f'[data-turn-id="{earlier_id}"]').press("Enter", timeout=5000)

    def release():
        assert len(held_routes) == 1
        held_routes[0].continue_()
        page.wait_for_function(
            "window.earlierHistoryResponseHandled === true", polling=50, timeout=5000
        )

    return release


@pytest.mark.parametrize("late_failure", [False, True], ids=["late-success", "late-error"])
def test_late_saved_turn_response_preserves_latest_selection(page, saved_turns, late_failure):
    base, good_turn, corrupt_id = saved_turns
    good_id = good_turn["turn_id"]
    earlier_id, latest_id = (corrupt_id, good_id) if late_failure else (good_id, corrupt_id)
    release = hold_saved_turn_request(page, base, earlier_id)
    page.locator(f'[data-turn-id="{latest_id}"]').press("Enter", timeout=5000)

    summary = page.locator("#turn-summary")
    expected_summary = (
        f"turn {good_id} ·" if late_failure else f"Saved turn {corrupt_id} could not be loaded."
    )
    expect(summary).to_contain_text(expected_summary)

    release()

    expect(summary).to_contain_text(expected_summary)
    download_button = page.get_by_role("button", name="Download turn JSON")
    if late_failure:
        expect(download_button).to_be_enabled()
    else:
        expect(download_button).to_be_disabled()


@pytest.mark.parametrize("late_failure", [False, True], ids=["late-success", "late-error"])
def test_late_saved_turn_response_preserves_new_run(page, saved_turns, late_failure):
    base, good_turn, corrupt_id = saved_turns
    earlier_id = corrupt_id if late_failure else good_turn["turn_id"]
    release = hold_saved_turn_request(page, base, earlier_id)

    run_button = page.get_by_role("button", name="Run task")
    page.locator("#task-input").fill("Calculate 13 * 17")
    with page.expect_response(f"{base}/api/run") as pending:
        run_button.click(timeout=5000)
    response = pending.value
    assert response.ok, response.text()
    new_turn = response.json()
    new_id = new_turn["turn_id"]

    summary = page.locator("#turn-summary")
    expect(summary).to_contain_text(f"Turn {new_id} ·")
    expect(run_button).to_be_enabled()
    release()

    expect(summary).to_contain_text(f"Turn {new_id} ·")
    expect(page.locator("#reply-text")).to_have_text(new_turn["reply"])
    expect(page.locator("#trace-list .trace-step")).to_have_count(len(new_turn["trace"]))

    download_button = page.get_by_role("button", name="Download turn JSON")
    expect(download_button).to_be_enabled()
    with page.expect_download() as pending_download:
        download_button.press("Enter", timeout=5000)
    download = pending_download.value
    assert download.suggested_filename == f"loop-agent-turn-{new_id}.json"
    assert json.loads(download.path().read_text(encoding="utf-8")) == new_turn
