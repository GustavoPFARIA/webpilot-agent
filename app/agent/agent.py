"""The agent loop: observe -> decide (LLM) -> check (guardrails) -> act (browser).

    page state ──► LLM picks ONE tool call ──► guardrails ──► browser ──► new page state
         ▲                                        │ block / ask a human        │
         └────────────────────────────────────────┴────────────────────────────┘

Stops when the model calls `done`, answers in plain text, a human rejects a
sensitive action, or the step budget runs out.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field

from app.agent import guardrails
from app.agent.llm import LLM
from app.agent.prompts import SYSTEM_PROMPT, start_message
from app.agent.tools import TOOL_NAMES, TOOLS
from app.browser.driver import ActionError, Browser
from app.config import Settings

log = logging.getLogger("webpilot")

Approver = Callable[[dict], Awaitable[bool]]


async def deny_all(_: dict) -> bool:
    return False


@dataclass
class Step:
    n: int
    action: str
    args: dict
    outcome: str
    ok: bool
    url: str
    thought: str = ""
    flags: list[str] = field(default_factory=list)
    latency_ms: int = 0
    screenshot: str | None = None  # base64 JPEG


@dataclass
class RunResult:
    status: str  # done | failed | rejected | max_steps | error
    answer: str
    steps: list[Step]
    usage: dict

    def to_dict(self, screenshots: bool = False) -> dict:
        d = asdict(self)
        if not screenshots:
            for s in d["steps"]:
                s.pop("screenshot", None)
        return d


class Agent:
    def __init__(
        self,
        llm: LLM,
        browser: Browser,
        settings: Settings,
        approver: Approver = deny_all,
        on_step: Callable[[Step], None] | None = None,
        screenshots: bool = False,
    ) -> None:
        self.llm = llm
        self.browser = browser
        self.s = settings
        self.approver = approver
        self.on_step = on_step or (lambda _: None)
        self.screenshots = screenshots
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "llm_calls": 0}

    async def observe(self) -> tuple[str, list[str], str]:
        state = await self.browser.state()
        flags = guardrails.detect_injection(state.text)
        # Redact the whole view, not just the text: typed values also show up in
        # element descriptions (an email field's value, "Signed in as ...").
        return guardrails.redact(state.render(flags), self.s.secrets), flags, state.url

    async def run(self, task: str) -> RunResult:
        steps: list[Step] = []
        page, flags, url = await self.observe()
        start_url = f"{self.s.public_url}/sandbox/"
        messages: list[dict] = [{"role": "user", "content": start_message(task, start_url, page)}]

        for n in range(1, self.s.max_steps + 1):
            t0 = time.perf_counter()
            resp = await asyncio.to_thread(self.llm.complete, [SYSTEM_PROMPT], messages, TOOLS)
            self._add_usage(resp.usage)
            messages.append({"role": "assistant", "content": resp.content})

            calls = resp.tool_calls
            if not calls:  # plain-text answer counts as finishing
                return self._finish("done", resp.text or "(no answer)", steps)

            call, extra = calls[0], calls[1:]
            name, args = call["name"], call["input"]
            if name == "done":
                ok = bool(args.get("success", True))
                step = Step(n, "done", args, "finished", ok, url, resp.text)
                self._record(steps, step)
                return self._finish("done" if ok else "failed", str(args.get("answer", "")), steps)

            outcome, ok, status = await self._act(name, args)
            page, flags, url = await self.observe()
            step = Step(n, name, args, outcome, ok, url, resp.text, flags, int((time.perf_counter() - t0) * 1000))
            if self.screenshots:
                shot = await self.browser.screenshot()
                step.screenshot = base64.b64encode(shot).decode() if shot else None
            self._record(steps, step)
            if status == "rejected":
                return self._finish("rejected", f"Stopped: a human rejected the action. {outcome}", steps)

            results = [
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps({"ok": ok, "result": outcome}) + "\n\nCurrent page:\n" + page,
                    **({} if ok else {"is_error": True}),
                }
            ]
            results += [
                {
                    "type": "tool_result",
                    "tool_use_id": c["id"],
                    "content": "Skipped: only one action per turn. Decide again from the new page state.",
                    "is_error": True,
                }
                for c in extra
            ]
            messages.append({"role": "user", "content": results})

        return self._finish("max_steps", f"Stopped after {self.s.max_steps} steps without finishing.", steps)

    async def _act(self, name: str, args: dict) -> tuple[str, bool, str]:
        """Run one action through the guardrails. Returns (outcome, ok, status)."""
        if name not in TOOL_NAMES:
            return f"Unknown tool '{name}'.", False, "error"
        try:
            if name == "navigate":
                blocked = guardrails.check_url(str(args.get("url", "")), self.s.allowed_domains)
                if blocked:
                    log.warning("blocked navigation: %s", args)
                    return blocked, False, "blocked"
                await self.browser.goto(args["url"])
                return f"Opened {args['url']}", True, "ok"

            if name == "scroll":
                await self.browser.scroll(args.get("direction", "down"))
                return f"Scrolled {args.get('direction', 'down')}", True, "ok"

            element_id = int(args["element_id"])
            element = (await self.browser.state()).element(element_id)
            if element is None:
                return f"No element [{element_id}] on this page.", False, "error"

            if name == "type_text":
                blocked = guardrails.check_typing(element, str(args.get("text", "")))
                if blocked:
                    return blocked, False, "blocked"

            reason = guardrails.approval_reason(name, element)
            if reason:
                approved = await self.approver(
                    {"action": name, "args": args, "element": element.describe(), "reason": reason}
                )
                if not approved:
                    return f"Human rejected: {reason}", False, "rejected"

            if name == "click":
                await self.browser.click(element_id)
                return f"Clicked [{element_id}] {element.text or element.label}".strip(), True, "ok"
            if name == "type_text":
                try:
                    real = guardrails.resolve_secrets(str(args["text"]), self.s.secrets)
                except KeyError as missing:
                    return f"Unknown secret {missing}.", False, "error"
                await self.browser.type(element_id, real, bool(args.get("submit", False)))
                return f"Typed into [{element_id}]" + (" and pressed Enter" if args.get("submit") else ""), True, "ok"
            if name == "select_option":
                await self.browser.select(element_id, str(args["value"]))
                return f"Selected '{args['value']}' in [{element_id}]", True, "ok"
        except ActionError as exc:
            return str(exc), False, "error"
        except (KeyError, ValueError, TypeError) as exc:
            return f"Invalid arguments for {name}: {exc}", False, "error"
        return "No-op", False, "error"

    def _record(self, steps: list[Step], step: Step) -> None:
        steps.append(step)
        log.info("step %s %s %s -> %s", step.n, step.action, json.dumps(step.args), step.outcome)
        self.on_step(step)

    def _add_usage(self, usage: dict) -> None:
        self.usage["llm_calls"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            self.usage[k] += int(usage.get(k, 0) or 0)

    def _finish(self, status: str, answer: str, steps: list[Step]) -> RunResult:
        return RunResult(status, answer, steps, dict(self.usage))
