import asyncio

from fastapi.testclient import TestClient

from app import sandbox
from app.main import app
from app.runs import Run

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_sandbox_search_and_product():
    r = client.get("/sandbox/search", params={"q": "running shoes"})
    assert "3 results" in r.text and "Trail Runner Lite" in r.text
    assert "Price: $149.00" in client.get("/sandbox/product/4").text


def test_sandbox_contact_is_recorded():
    sandbox.reset()
    client.post("/sandbox/contact", data={"name": "Ana", "email": "a@x.io", "message": "Hi"})
    assert client.get("/sandbox/_state").json()["contact"] == [{"name": "Ana", "email": "a@x.io", "message": "Hi"}]


def test_sandbox_login_rejects_wrong_password():
    sandbox.reset()
    c = TestClient(app)
    r = c.post("/sandbox/login", data={"email": "demo@acme.test", "password": "nope"}, follow_redirects=False)
    assert r.headers["location"].endswith("error=1")


def test_task_validation():
    assert client.post("/api/runs", json={"task": ""}).status_code == 422


def test_unknown_run():
    assert client.get("/api/runs/nope").status_code == 404
    assert client.post("/api/runs/nope/approval", json={"approve": True}).status_code == 404


async def test_run_waits_for_a_human_decision():
    run = Run(id="r1", task="buy")
    waiting = asyncio.create_task(run.ask({"reason": "Place order"}))
    await asyncio.sleep(0)
    assert run.status == "awaiting_approval" and run.pending["reason"] == "Place order"
    assert run.decide(True)
    assert await waiting is True
    assert run.status == "running" and run.pending is None
    assert run.decide(False) is False  # nothing pending anymore
