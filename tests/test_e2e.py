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


@pytest.mark.parametrize("case_id", ["search-cheapest", "login-secrets", "reviews-with-injection", "buy-rejected"])
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
