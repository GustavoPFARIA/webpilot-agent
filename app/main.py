import hmac
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import sandbox, telemetry
from app.config import get_settings
from app.runs import LimitError, manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
telemetry.setup(get_settings().otel_console)

STATIC = Path(__file__).parent / "static"
LOOPBACK = {"127.0.0.1", "::1"}

app = FastAPI(
    title="WebPilot Agent",
    version="1.3.1",
    description="AI agent that completes tasks in a real browser, with guardrails and human approval.",
)
app.include_router(sandbox.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Strict headers for the app's own pages (OWASP A02:2025 security misconfiguration). The sandbox is excluded on
# purpose: it plays "some website on the internet"; /docs needs Swagger's CDN.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(("/sandbox", "/docs", "/redoc")):
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", CSP)
    return response


def current_user(request: Request, authorization: str | None = Header(default=None)) -> str:
    """Bearer-token auth (OWASP A01/A07). Without API_KEYS configured, only this
    machine may call the API: safe for local use, closed when deployed."""
    keys = get_settings().api_keys
    if keys:
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
        for key, user in keys.items():
            if token and hmac.compare_digest(key.encode(), token.encode()):
                return user
        raise HTTPException(401, "Missing or invalid API token", headers={"WWW-Authenticate": "Bearer"})
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(401, "Remote access requires API_KEYS to be configured")
    return "local"


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
    return {
        "status": "ok",
        "llm_provider": s.resolved_provider(),
        "allowed_domains": s.allowed_domains,
        "auth": "api_keys" if s.api_keys else "loopback_only",
    }


@app.post("/api/runs", status_code=202)
async def create_run(body: RunRequest, request: Request, user: str = Depends(current_user)):
    try:
        run = manager.start(body.task, owner=user, base_url=str(request.base_url).rstrip("/"))
    except LimitError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "60"}) from exc
    return {"id": run.id, "status": run.status}


@app.get("/api/runs")
def list_runs(user: str = Depends(current_user)):
    return [{"id": r.id, "task": r.task, "status": r.status, "created_at": r.created_at} for r in manager.list(user)]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: str = Depends(current_user)):
    run = manager.get(run_id, user)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run.to_dict()


@app.post("/api/runs/{run_id}/approval")
def decide(run_id: str, body: Approval, user: str = Depends(current_user)):
    run = manager.get(run_id, user)
    if run is None:
        raise HTTPException(404, "Run not found")
    if not run.decide(body.approve):
        raise HTTPException(409, "This run is not waiting for approval")
    return {"id": run.id, "approved": body.approve}
