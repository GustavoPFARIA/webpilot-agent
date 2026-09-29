import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import sandbox
from app.config import get_settings
from app.runs import manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

STATIC = Path(__file__).parent / "static"

app = FastAPI(
    title="WebPilot Agent",
    version="1.0.0",
    description="AI agent that completes tasks in a real browser, with guardrails and human approval.",
)
app.include_router(sandbox.router)


class RunRequest(BaseModel):
    task: str = Field(min_length=3, max_length=500)


class Approval(BaseModel):
    approve: bool


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "llm_provider": s.llm_provider, "allowed_domains": s.allowed_domains}


@app.post("/api/runs", status_code=202)
async def create_run(body: RunRequest):
    run = manager.start(body.task)
    return {"id": run.id, "status": run.status}


@app.get("/api/runs")
def list_runs():
    return [
        {"id": r.id, "task": r.task, "status": r.status, "created_at": r.created_at}
        for r in reversed(manager.runs.values())
    ]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = manager.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run.to_dict()


@app.post("/api/runs/{run_id}/approval")
def decide(run_id: str, body: Approval):
    run = manager.runs.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if not run.decide(body.approve):
        raise HTTPException(409, "This run is not waiting for approval")
    return {"id": run.id, "approved": body.approve}
