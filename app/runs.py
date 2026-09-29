"""Background runs: each task gets its own isolated browser and agent, and can
pause mid-run waiting for a human to approve a sensitive action.

Runs belong to the user who started them: nobody else can see or approve them.
Per-user rate and concurrency limits and a wall-clock timeout bound the cost."""

import asyncio
import logging
import secrets
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.agent.agent import Agent, Step
from app.agent.guardrails import url_policy
from app.agent.llm import get_llm
from app.browser.driver import PlaywrightBrowser
from app.config import get_settings

log = logging.getLogger("webpilot")


@dataclass
class Run:
    id: str
    task: str
    owner: str = "local"
    base_url: str | None = None  # where the user reached this server; the default start page
    status: str = "running"  # running | awaiting_approval | done | failed | rejected | max_steps | error
    answer: str = ""
    steps: list[Step] = field(default_factory=list)
    pending: dict | None = None
    usage: dict = field(default_factory=dict)
    model: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    _decision: asyncio.Future | None = None

    async def ask(self, request: dict) -> bool:
        """Approver passed to the agent: park the run until a human decides (or it times out)."""
        self.pending, self.status = request, "awaiting_approval"
        self._decision = asyncio.get_running_loop().create_future()
        try:
            return await asyncio.wait_for(self._decision, get_settings().approval_timeout_s)
        except TimeoutError:
            return False
        finally:
            self.pending, self.status, self._decision = None, "running", None

    def decide(self, approve: bool) -> bool:
        if self._decision is None or self._decision.done():
            return False
        self._decision.set_result(approve)
        return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "owner": self.owner,
            "status": self.status,
            "answer": self.answer,
            "steps": [asdict(s) for s in self.steps],
            "pending": self.pending,
            "usage": self.usage,
            "model": self.model,
            "created_at": self.created_at,
        }


ACTIVE = ("running", "awaiting_approval")


class LimitError(Exception):
    """The user hit a rate or concurrency limit (HTTP 429)."""


class RunManager:
    def __init__(self, max_runs: int = 200) -> None:
        self.runs: dict[str, Run] = {}
        self.max_runs = max_runs
        self._tasks: set[asyncio.Task] = set()
        self._starts: dict[str, deque[float]] = defaultdict(deque)

    def get(self, run_id: str, owner: str) -> Run | None:
        run = self.runs.get(run_id)
        # Another user's run is reported as "not found": don't even confirm it exists.
        return run if run is not None and run.owner == owner else None

    def list(self, owner: str) -> list[Run]:
        return [r for r in reversed(self.runs.values()) if r.owner == owner]

    def _check_limits(self, owner: str) -> None:
        s = get_settings()
        window, now = self._starts[owner], time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= s.runs_per_minute:
            raise LimitError(f"Rate limit: at most {s.runs_per_minute} runs per minute.")
        if sum(r.owner == owner and r.status in ACTIVE for r in self.runs.values()) >= s.max_concurrent_runs:
            raise LimitError(f"At most {s.max_concurrent_runs} runs at a time; wait for one to finish.")
        window.append(now)

    def start(self, task: str, owner: str = "local", base_url: str | None = None) -> Run:
        self._check_limits(owner)
        run = Run(id=secrets.token_urlsafe(12), task=task, owner=owner, base_url=base_url)
        self.runs[run.id] = run
        finished = [k for k, r in self.runs.items() if r.status not in ACTIVE]
        while len(self.runs) > self.max_runs and finished:  # keep memory bounded
            self.runs.pop(finished.pop(0))
        t = asyncio.create_task(self._execute(run))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return run

    async def _execute(self, run: Run) -> None:
        s = get_settings()
        if not s.public_url and run.base_url:
            s = s.model_copy(update={"public_url": run.base_url})
        try:
            llm = get_llm()
            run.model = llm.name
            policy = url_policy(s.allowed_domains, s.browser_denied_paths, s.public_url)
            async with PlaywrightBrowser.launch(s.headless, s.browser_channel, policy) as browser:
                agent = Agent(llm, browser, s, approver=run.ask, on_step=run.steps.append, screenshots=True)
                result = await asyncio.wait_for(agent.run(run.task), s.run_timeout_s)
            run.status, run.answer, run.usage = result.status, result.answer, result.usage
        except TimeoutError:
            run.status, run.answer = "error", f"Run timed out after {s.run_timeout_s:.0f} s."
        except Exception as exc:  # surface failures to the UI instead of dying silently
            log.exception("run %s failed", run.id)
            run.status, run.answer = "error", f"Run failed: {exc}"


manager = RunManager()
