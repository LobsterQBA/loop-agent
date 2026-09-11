import json

from agent_system.build_site import build_site


def test_recorded_site_uses_real_fresh_process_results_and_relative_assets(tmp_path):
    site = tmp_path / "site"
    build_site(site)
    html = (site / "index.html").read_text()
    assert 'data-preview="recorded"' in html
    assert 'href="./style.css"' in html
    assert 'src="./app.js"' in html
    assert 'src="/app.js"' not in html
    assert "it does not run an AI model" in html
    assert "See how an agent uses tools to finish a task." in html
    assert "2. recall after restart</button>" in html
    assert "3. try a failure</button>" in html
    examples = json.loads((site / "examples.json").read_text())["examples"]
    first, recall, failure = examples
    assert first["turn"]["tool_calls"] == 2
    assert "launch score = 391" in recall["turn"]["reply"]
    assert "did not save" in failure["turn"]["reply"]
    assert failure["memory"]["memories"] == first["memory"]["memories"]
    assert [len(item["memory"]["turns"]) for item in examples] == [1, 2, 3]
