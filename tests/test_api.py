import asyncio

import pytest
from fastapi.testclient import TestClient

from app import sandbox
from app.config import get_settings
from app.main import app
from app.runs import LimitError, Run, RunManager

local = TestClient(app, client=("127.0.0.1", 50000))
remote = TestClient(app, client=("203.0.113.7", 50000))


@pytest.fixture
def api_keys(monkeypatch):
    monkeypatch.setattr(get_settings(), "api_keys", {"token-alice": "alice", "token-bob": "bob"})


@pytest.fixture
def no_browser(monkeypatch):
    """Start runs without launching a browser: they stay 'running'."""

    async def idle(self, run):
        await asyncio.sleep(3600)

    monkeypatch.setattr(RunManager, "_execute", idle)


def test_health():
    assert local.get("/health").json()["auth"] == "loopback_only"


def test_security_headers_on_app_pages():
    h = local.get("/").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert "script-src 'self'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert local.get("/static/app.js").status_code == 200


def test_sandbox_search_and_product():
    r = local.get("/sandbox/search", params={"q": "running shoes"})
    assert "3 results" in r.text and "Trail Runner Lite" in r.text
    assert "Price: $149.00" in local.get("/sandbox/product/4").text


def test_sandbox_contact_is_recorded():
    sandbox.reset()
    local.post("/sandbox/contact", data={"name": "Ana", "email": "a@x.io", "message": "Hi"})
    assert local.get("/sandbox/_state").json()["contact"] == [{"name": "Ana", "email": "a@x.io", "message": "Hi"}]


def test_sandbox_login_rejects_wrong_password():
    sandbox.reset()
    r = local.post("/sandbox/login", data={"email": "demo@acme.test", "password": "nope"}, follow_redirects=False)
    assert r.headers["location"].endswith("error=1")


def test_task_validation():
    assert local.post("/api/runs", json={"task": ""}).status_code == 422


def test_unknown_run():
    assert local.get("/api/runs/nope").status_code == 404
    assert local.post("/api/runs/nope/approval", json={"approve": True}).status_code == 404


# --- authentication and authorization (OWASP A01 / A07) ---------------------


def test_without_api_keys_only_loopback_is_allowed():
    assert remote.get("/api/runs").status_code == 401
    assert local.get("/api/runs").status_code == 200


def test_api_keys_required_when_configured(api_keys):
    assert local.get("/api/runs").status_code == 401  # even from loopback
    assert local.get("/api/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = remote.get("/api/runs", headers={"Authorization": "Bearer token-alice"})
    assert r.status_code == 200


def test_users_cannot_see_or_approve_each_others_runs(api_keys, no_browser):
    alice = {"Authorization": "Bearer token-alice"}
    bob = {"Authorization": "Bearer token-bob"}
    run_id = remote.post("/api/runs", json={"task": "Buy the Aurora Headphones."}, headers=alice).json()["id"]

    assert remote.get(f"/api/runs/{run_id}", headers=alice).status_code == 200
    assert remote.get(f"/api/runs/{run_id}", headers=bob).status_code == 404
    assert remote.post(f"/api/runs/{run_id}/approval", json={"approve": True}, headers=bob).status_code == 404
    assert run_id not in [r["id"] for r in remote.get("/api/runs", headers=bob).json()]


# --- abuse limits (OWASP LLM10) ---------------------------------------------


def test_concurrency_and_rate_limits(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "max_concurrent_runs", 1)
    monkeypatch.setattr(s, "runs_per_minute", 2)
    m = RunManager()
    m.runs["a"] = Run(id="a", task="t", owner="u")  # one run already in progress
    with pytest.raises(LimitError, match="at a time"):
        m._check_limits("u")
    m.runs["a"].status = "done"
    m._check_limits("u")
    m._check_limits("u")
    with pytest.raises(LimitError, match="per minute"):
        m._check_limits("u")
    m._check_limits("someone-else")  # limits are per user


def test_rate_limit_returns_429(monkeypatch, no_browser):
    monkeypatch.setattr(get_settings(), "runs_per_minute", 0)
    r = local.post("/api/runs", json={"task": "anything"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


async def test_run_waits_for_a_human_decision():
    run = Run(id="r1", task="buy")
    waiting = asyncio.create_task(run.ask({"reason": "Place order"}))
    await asyncio.sleep(0)
    assert run.status == "awaiting_approval" and run.pending["reason"] == "Place order"
    assert run.decide(True)
    assert await waiting is True
    assert run.status == "running" and run.pending is None
    assert run.decide(False) is False  # nothing pending anymore


def test_sandbox_escapes_user_input():
    r = local.get("/sandbox/search", params={"q": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_sandbox_rejects_forged_session_ids():
    forged = TestClient(app, client=("127.0.0.1", 50000), cookies={"acme_sid": "x; Path=/; evil"})
    r = forged.get("/sandbox/")
    assert "evil" not in r.headers["set-cookie"]


@pytest.mark.parametrize(
    ("to", "expected"),
    [
        ("http://evil.example/blog", "http://evil.example/blog"),  # the eval's trap still works
        ("https://www.google.com/", "/sandbox/"),  # but real sites are never a target
        ("//attacker.com/x", "/sandbox/"),
        ("javascript:alert(1)", "/sandbox/"),
        ("/sandbox/help", "/sandbox/help"),
        ("/api/runs", "/sandbox/"),
    ],
)
def test_open_redirect_is_limited_to_reserved_domains(to, expected):
    r = local.get("/sandbox/go", params={"to": to}, follow_redirects=False)
    assert r.headers["location"] == expected


def test_login_rotates_the_session_id():
    sandbox.reset()
    c = TestClient(app, client=("127.0.0.1", 50000))
    c.get("/sandbox/")
    before = c.cookies["acme_sid"]
    s = get_settings().secrets
    c.post("/sandbox/login", data={"email": s["store_username"], "password": s["store_password"]})
    assert c.cookies["acme_sid"] != before
    assert before not in sandbox.SESSIONS
    assert "Loyalty points" in c.get("/sandbox/account").text
