"""Background runs: each task gets its own isolated browser and agent, and can
pause mid-run waiting for a human to approve a sensitive action."""

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.agent.agent import Agent, Step
from app.agent.llm import get_llm
from app.browser.driver import PlaywrightBrowser
from app.config import get_settings

log = logging.getLogger("webpilot")


@dataclass
class Run:
    id: str
    task: str
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
            "status": self.status,
            "answer": self.answer,
            "steps": [asdict(s) for s in self.steps],
            "pending": self.pending,
            "usage": self.usage,
            "model": self.model,
            "created_at": self.created_at,
        }


class RunManager:
    def __init__(self, max_runs: int = 50) -> None:
        self.runs: dict[str, Run] = {}
        self.max_runs = max_runs
        self._tasks: set[asyncio.Task] = set()

    def start(self, task: str) -> Run:
        run = Run(id=uuid.uuid4().hex[:12], task=task)
        self.runs[run.id] = run
        while len(self.runs) > self.max_runs:  # keep memory bounded
            self.runs.pop(next(iter(self.runs)))
        t = asyncio.create_task(self._execute(run))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return run

    async def _execute(self, run: Run) -> None:
        s = get_settings()
        try:
            llm = get_llm()
            run.model = llm.name
            async with PlaywrightBrowser.launch(s.headless, s.browser_channel) as browser:
                agent = Agent(llm, browser, s, approver=run.ask, on_step=run.steps.append, screenshots=True)
                result = await agent.run(run.task)
            run.status, run.answer, run.usage = result.status, result.answer, result.usage
        except Exception as exc:  # surface failures to the UI instead of dying silently
            log.exception("run %s failed", run.id)
            run.status, run.answer = "error", f"Run failed: {exc}"


manager = RunManager()
