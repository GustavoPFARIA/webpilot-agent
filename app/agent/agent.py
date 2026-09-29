"""The agent loop: observe -> decide (LLM) -> check (guardrails) -> act (browser).

    page state ──► LLM picks ONE tool call ──► guardrails ──► browser ──► new page state
         ▲                                        │ block / ask a human        │
         └────────────────────────────────────────┴────────────────────────────┘

Stops when the model calls `done`, answers in plain text, a human rejects a
sensitive action, the model API fails, or the step / token / cost budget runs out.
Every run, LLM call and action is an OpenTelemetry span (see app/telemetry.py).
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.agent import guardrails
from app.agent.llm import LLM
from app.agent.prompts import SYSTEM_PROMPT, start_message
from app.agent.tools import TOOL_NAMES, TOOLS
from app.browser.driver import ActionError, Browser
from app.config import Settings
from app.telemetry import tracer

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
    status: str  # done | failed | rejected | max_steps | budget_exceeded | error
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
        self.usage: dict[str, Any] = {
            "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "llm_calls": 0, "cost_usd": 0.0,
        }  # fmt: skip

    def url_policy(self, url: str) -> str | None:
        return guardrails.url_policy(self.s.allowed_domains, self.s.browser_denied_paths)(url)

    async def observe(self) -> tuple[str, list[str], str]:
        state = await self.browser.state()
        flags = guardrails.detect_injection(state.text)
        # Redact the whole view, not just the text: typed values also show up in
        # element descriptions (an email field's value, "Signed in as ...").
        return guardrails.redact(state.render(flags), self.s.secrets), flags, state.url

    async def run(self, task: str) -> RunResult:
        with tracer.start_as_current_span("webpilot.run") as span:
            span.set_attribute("webpilot.task", task[:200])
            span.set_attribute("gen_ai.request.model", self.llm.name)
            result = await self._run(task)
            span.set_attribute("webpilot.status", result.status)
            span.set_attribute("webpilot.steps", len(result.steps))
            span.set_attribute("webpilot.cost_usd", result.usage["cost_usd"])
            return result

    async def _run(self, task: str) -> RunResult:
        steps: list[Step] = []
        page, flags, url = await self.observe()
        start_url = f"{self.s.public_url}/sandbox/"
        messages: list[dict] = [{"role": "user", "content": start_message(task, start_url, page)}]

        for n in range(1, self.s.max_steps + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._complete(messages)
            except Exception as exc:  # provider down after SDK retries, bad key, ...
                log.exception("LLM call failed")
                return self._finish("error", f"The model API failed: {type(exc).__name__}: {exc}", steps)
            over = self._over_budget()
            if over:
                return self._finish("budget_exceeded", over, steps)
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

            with tracer.start_as_current_span(f"webpilot.action.{name}") as span:
                outcome, ok, status = await self._act(name, args)
                blocked = self.browser.drain_blocked()
                if blocked:  # e.g. a clicked link or redirect tried to leave the allow-list
                    outcome += ". Blocked by network policy: " + "; ".join(blocked)
                    ok = False
                span.set_attribute("webpilot.ok", ok)
                span.set_attribute("webpilot.outcome", outcome[:200])
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
                blocked = self.url_policy(str(args.get("url", "")))
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

    async def _complete(self, messages: list[dict]):
        with tracer.start_as_current_span("gen_ai.chat") as span:
            span.set_attribute("gen_ai.request.model", self.llm.name)
            resp = await asyncio.to_thread(self.llm.complete, [SYSTEM_PROMPT], messages, TOOLS)
            span.set_attribute("gen_ai.usage.input_tokens", int(resp.usage.get("input_tokens", 0) or 0))
            span.set_attribute("gen_ai.usage.output_tokens", int(resp.usage.get("output_tokens", 0) or 0))
            if resp.usage.get("model"):
                span.set_attribute("gen_ai.response.model", resp.usage["model"])
        self._add_usage(resp.usage)
        return resp

    def _add_usage(self, usage: dict) -> None:
        self.usage["llm_calls"] += 1
        if usage.get("model"):
            self.usage.setdefault("models", {})
            self.usage["models"][usage["model"]] = self.usage["models"].get(usage["model"], 0) + 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            self.usage[k] += int(usage.get(k, 0) or 0)
        u = self.usage
        p_in, p_out, p_cache = self.s.prices()
        u["cost_usd"] = round(
            (u["input_tokens"] * p_in + u["output_tokens"] * p_out + u["cache_read_input_tokens"] * p_cache)
            / 1_000_000,
            6,
        )

    def _over_budget(self) -> str | None:
        u = self.usage
        tokens = u["input_tokens"] + u["output_tokens"] + u["cache_read_input_tokens"]
        if tokens > self.s.max_tokens_per_run:
            return f"Stopped: token budget exceeded ({tokens} > {self.s.max_tokens_per_run})."
        if u["cost_usd"] > self.s.max_cost_per_run_usd:
            return f"Stopped: cost budget exceeded (${u['cost_usd']:.4f} > ${self.s.max_cost_per_run_usd:.2f})."
        return None

    def _finish(self, status: str, answer: str, steps: list[Step]) -> RunResult:
        return RunResult(status, answer, steps, dict(self.usage))
