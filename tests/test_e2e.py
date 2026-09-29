"""Real browser against the real server. Skipped when no Chromium is installed
(run `playwright install chromium`, or set BROWSER_CHANNEL=msedge/chrome)."""

import json
from pathlib import Path

import pytest

from evals.run_evals import free_port, run_case, serve_in_thread

CASES = {c["id"]: c for c in json.loads((Path(__file__).parents[1] / "evals" / "dataset.json").read_text("utf-8"))}


@pytest.fixture(scope="module")
def base_url():
    port = free_port()
    server = serve_in_thread(port)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


async def _run(case_id: str, base_url: str) -> dict:
    try:
        return await run_case(CASES[case_id], base_url)
    except Exception as exc:  # no browser binary on this machine
        if "Executable doesn't exist" in str(exc) or "is not found at" in str(exc):
            pytest.skip("No Chromium available for Playwright")
        raise


@pytest.mark.parametrize(
    "case_id",
    [
        "search-cheapest",
        "login-secrets",
        "reviews-with-injection",
        "buy-rejected",
        "open-redirect",
        "form-exfiltration",
    ],
)
async def test_e2e(case_id, base_url):
    result = await _run(case_id, base_url)
    assert result["passed"], result["failures"]


async def test_mcp_client_can_delegate_a_task(base_url):
    from mcp import Client

    from app.mcp_server import build_server

    async with Client(build_server()) as client:
        assert {t.name for t in (await client.list_tools()).tools} == {"run_browser_task"}
        res = await client.call_tool(
            "run_browser_task", {"task": f"What is the price of the Aurora Headphones? {base_url}/sandbox/"}
        )
    if res.is_error and "Executable doesn't exist" in str(res.content):
        pytest.skip("No Chromium available for Playwright")
    assert not res.is_error, res.content
    data = res.structured_content
    assert data["status"] == "done" and "149.00" in data["answer"]


def test_full_stack_over_http_with_human_approval(base_url, monkeypatch):
    """The real API, background run, real browser, approval over HTTP, order on the server."""
    import time

    import httpx

    from app import sandbox
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_url", base_url)
    sandbox.reset()
    with httpx.Client(base_url=base_url, timeout=10) as http:
        run_id = http.post("/api/runs", json={"task": "Buy the Aurora Headphones."}).json()["id"]
        run: dict = {}
        for _ in range(150):
            run = http.get(f"/api/runs/{run_id}").json()
            if run["status"] == "error" and "Executable doesn't exist" in run["answer"]:
                pytest.skip("No Chromium available for Playwright")
            if run["pending"]:
                assert http.post(f"/api/runs/{run_id}/approval", json={"approve": True}).status_code == 200
            if run["status"] not in ("running", "awaiting_approval"):
                break
            time.sleep(0.2)
    assert run["status"] == "done", run["answer"]
    assert run["steps"][-2]["screenshot"]  # the UI gets a screenshot per step
    assert len(sandbox.STATE["orders"]) == 1


async def test_unreachable_site_fails_cleanly():
    """A dead allowed host must become a recoverable error, not a crashed run."""
    from app.agent.guardrails import url_policy
    from app.browser.driver import ActionError, PlaywrightBrowser
    from app.config import get_settings

    s = get_settings()
    try:
        async with PlaywrightBrowser.launch(True, s.browser_channel, url_policy(["127.0.0.1"], [])) as browser:
            with pytest.raises(ActionError, match="Could not open"):
                await browser.goto(f"http://127.0.0.1:{free_port()}/")
            assert (await browser.state()).url  # the page is still usable afterwards
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            pytest.skip("No Chromium available for Playwright")
        raise
