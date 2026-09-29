"""LLM providers behind one interface, using the Anthropic Messages format
(content blocks with `text`, `tool_use` and `tool_result`).

- `AnthropicLLM` calls Claude with native tool use and prompt caching.
- `OpenAILLM` calls OpenAI Chat Completions with function calling.
- `ScriptedLLM` is a deterministic browsing policy speaking the same protocol.
  It reads the same page-state text a real model gets and emits one tool call
  per turn, so the whole loop (browser, guardrails, approvals, evals) runs
  offline in the demo and in CI. It is a stand-in, not a general agent: it
  knows a handful of task shapes (search, compare, read, log in, forms, buy).
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.config import get_settings


@dataclass
class LLMResponse:
    content: list[dict]
    usage: dict

    @property
    def tool_calls(self) -> list[dict]:
        return [b for b in self.content if b["type"] == "tool_use"]

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b["type"] == "text").strip()


class LLM(Protocol):
    name: str

    def complete(self, system: list[str], messages: list[dict], tools: list[dict]) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, timeout: float = 60, max_retries: int = 3):
        import anthropic

        # The SDK retries 408/409/429/5xx and connection errors with exponential backoff.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model = model
        self.name = model

    def complete(self, system: list[str], messages: list[dict], tools: list[dict]) -> LLMResponse:
        # Prompt caching: the breakpoint covers tools + system prompt, identical on every
        # step, so each step after the first reads them at a fraction of the input price.
        blocks = [{"type": "text", "text": system[0], "cache_control": {"type": "ephemeral"}}]
        blocks += [{"type": "text", "text": text} for text in system[1:]]
        # Internal messages are plain dicts in the Messages API shape; the SDK's
        # TypedDicts describe the same structure.
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=cast(Any, blocks),
            messages=cast(Any, messages),
            tools=cast(Any, tools),
        )
        content = [b.model_dump(include={"type", "text", "id", "name", "input"}) for b in resp.content]
        return LLMResponse(
            content=[c for c in content if c["type"] in ("text", "tool_use")],
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "cache_read_input_tokens": resp.usage.cache_read_input_tokens or 0,
            },
        )


class OpenAILLM:
    """Translates the internal (Anthropic-style) messages to OpenAI and back, so
    tools, guardrails, evals and traces stay provider-agnostic."""

    def __init__(self, api_key: str, model: str, timeout: float = 60, max_retries: int = 3):
        import openai

        self.client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self.model = model
        self.name = model

    @staticmethod
    def to_openai(system: list[str], messages: list[dict], tools: list[dict]) -> tuple[list[dict], list[dict]]:
        out: list[dict] = [{"role": "system", "content": "\n\n".join(system)}]
        for m in messages:
            if isinstance(m["content"], str):
                out.append({"role": m["role"], "content": m["content"]})
            elif m["role"] == "assistant":
                text = "".join(b["text"] for b in m["content"] if b["type"] == "text") or None
                calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                    }
                    for b in m["content"]
                    if b["type"] == "tool_use"
                ]
                out.append({"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})})
            else:
                out += [
                    {"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]}
                    for b in m["content"]
                    if b["type"] == "tool_result"
                ]
        fns = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in tools
        ]
        return out, fns

    def complete(self, system: list[str], messages: list[dict], tools: list[dict]) -> LLMResponse:
        oa_messages, oa_tools = self.to_openai(system, messages, tools)
        resp = self.client.chat.completions.create(
            model=self.model, messages=cast(Any, oa_messages), tools=cast(Any, oa_tools)
        )
        msg = resp.choices[0].message
        content: list[dict] = [{"type": "text", "text": msg.content}] if msg.content else []
        content += [
            {"type": "tool_use", "id": c.id, "name": c.function.name, "input": _parse_args(c.function.arguments)}
            for c in msg.tool_calls or []
            if c.type == "function"  # custom (free-text) tool calls are not used by this agent
        ]
        usage = resp.usage
        details = usage.prompt_tokens_details if usage else None
        return LLMResponse(
            content=content,
            usage={
                "input_tokens": usage.prompt_tokens if usage else 0,
                "output_tokens": usage.completion_tokens if usage else 0,
                "cache_read_input_tokens": (details.cached_tokens or 0) if details else 0,
            },
        )


def _parse_args(raw: str | None) -> dict:
    """Models occasionally emit malformed JSON arguments. Return {} so the agent
    reports "invalid arguments" back to the model instead of crashing the run."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


# --- deterministic scripted policy ------------------------------------------


@dataclass
class View:
    url: str
    title: str
    elements: list[tuple[int, str]]  # (id, lowercase description line)
    text: str
    last_ok: bool = True
    last_result: str = ""
    warned: bool = False  # the agent flagged a prompt-injection attempt on this page

    def find(self, *needles: str) -> int | None:
        for i, line in self.elements:
            if all(n in line for n in needles):
                return i
        return None


def parse_view(content: str) -> View:
    head = content.split("\nCurrent page:\n", 1)
    page = head[-1]
    last_ok, last_result = True, ""
    if len(head) == 2 and head[0].startswith("{"):
        meta = json.loads(head[0])
        last_ok, last_result = meta["ok"], meta["result"]
    url = re.search(r"^URL: (.*)$", page, re.M)
    title = re.search(r"^Title: (.*)$", page, re.M)
    elements = [(int(m.group(1)), m.group(0).lower()) for m in re.finditer(r"^\[(\d+)\] .*$", page, re.M)]
    text = page.split("<<<PAGE\n", 1)[-1].rsplit("\nPAGE>>>", 1)[0]
    warned = "SECURITY WARNING:" in page.split("<<<PAGE", 1)[0]
    return View(
        url.group(1) if url else "", title.group(1) if title else "", elements, text, last_ok, last_result, warned
    )


QUERY_RE = re.compile(
    r"(?:search(?: the [\w ]+? store)? for|price of|reviews? (?:of|for)|buy|order|purchase)\s+(?:the\s+|a\s+)?"
    r"(.+?)(?=\s+(?:and|on|in|at|from|then)\b|[?.!,]|$)",
    re.I,
)
FIELD_RE = re.compile(r"\b(name|email|message)\s*[:=]\s*(.+?)(?=,\s*(?:name|email|message)\s*[:=]|$)", re.I)


def _blocked_reason(view: View) -> str:
    m = re.search(r"Blocked by network policy: (\S+) \((.+)\)$", view.last_result)
    if not m:
        return view.last_result
    return f"The page tried to send the browser to {m.group(1)}. {m.group(2)}"


def _line(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else ""


def _query(task: str) -> str:
    quoted = re.search(r"(?:^|\s)[\"'“‘](.+?)[\"'”’]", task)  # noqa: RUF001 (typographic quotes on purpose)
    if quoted:
        return quoted.group(1)
    m = QUERY_RE.search(task)
    return m.group(1).strip() if m else ""


class ScriptedLLM:
    name = "scripted-policy"

    def __init__(self) -> None:
        self._n = 0

    def _call(self, name: str, **args) -> LLMResponse:
        self._n += 1
        return LLMResponse([{"type": "tool_use", "id": f"toolu_s{self._n}", "name": name, "input": args}], {})

    def _done(self, answer: str, success: bool = True) -> LLMResponse:
        return self._call("done", answer=answer, success=success)

    def complete(self, system: list[str], messages: list[dict], tools: list[dict]) -> LLMResponse:
        first = messages[0]["content"]
        task = _line(first, r"^Task: (.*)$")
        last = messages[-1]["content"]
        view = parse_view(last if isinstance(last, str) else last[0]["content"])
        history = [b for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"]
        typed = {b["input"].get("text") for b in history if b["name"] == "type_text"}
        t = task.lower()

        if not view.last_ok and history and history[-1]["name"] == "navigate":
            return self._done(f"I couldn't complete the task: {view.last_result}", success=False)
        if len(history) >= 12:
            return self._done("I couldn't finish the task within my step budget.", success=False)
        if view.url in ("", "about:blank"):
            url = re.search(r"https?://\S+", task)
            start = _line(first, r"^Start URL[^:]*: (\S+)$")
            return self._call("navigate", url=url.group(0).rstrip(".,") if url else start)

        low = view.text.lower()
        query = _query(task)

        if "newsletter" in t:
            return self._newsletter(task, view, typed)
        if re.search(r"\b(click|open|follow)\b", t) and "link" in t:
            return self._follow_link(query, view, history)
        if re.search(r"\b(log ?in|sign in|loyalty|my account)\b", t):
            return self._login(view, typed)
        if "contact" in t:
            return self._contact(task, view, typed)
        if re.search(r"\b(buy|order|purchase)\b", t):
            return self._buy(query, view, low)
        if re.search(r"\b(return|refund|shipping)\b", t):
            if "return policy" in low:
                sentence = re.search(r"[^.\n]*\d+ days[^.\n]*\.", view.text)
                return self._done(sentence.group(0).strip() if sentence else "See the store's Help page.")
            return self._click_or_fail(view, '"help')

        if re.search(r"\b(cheapest|lowest price|least expensive)\b", t):
            if "results for" in low:
                items = re.findall(r"^(.+?) — \$([\d.]+)$", view.text, re.M)
                if not items:
                    return self._done(f"No products found for '{query}'.", success=False)
                name, price = min(items, key=lambda x: float(x[1]))
                return self._done(f"The cheapest {query} is {name.strip()} at ${float(price):.2f}.")
            return self._search(query, view, typed)

        # product-page tasks: price, reviews
        if self._on_product(query, view):
            if "review" in t:
                return self._done(self._summarize_reviews(view))
            price = re.search(r"Price: \$([\d.]+)", view.text)
            name = view.title.split(" · ")[0]
            return self._done(f"{name} costs ${float(price.group(1)):.2f}." if price else "No price shown.")
        return self._open_product(query, view, typed)

    # --- skills ---

    def _search(self, query: str, view: View, typed: set) -> LLMResponse:
        box = view.find("input(search)")
        if box is None or (query in typed and "results for" in view.text.lower()):
            return self._done(f"I couldn't search for '{query}' on this site.", success=False)
        return self._call("type_text", element_id=box, text=query, submit=True)

    @staticmethod
    def _on_product(query: str, view: View) -> bool:
        return "price: $" in view.text.lower() and query.lower() in view.title.lower()

    def _open_product(self, query: str, view: View, typed: set) -> LLMResponse:
        if not query:
            return self._done("I couldn't tell which product you mean.", success=False)
        if "results for" in view.text.lower():
            link = view.find(f'"{query.lower()}')
            if link is None:
                return self._done(f"I couldn't find '{query}' in the store.", success=False)
            return self._call("click", element_id=link)
        return self._search(query, view, typed)

    def _click_or_fail(self, view: View, *needles: str) -> LLMResponse:
        target = view.find(*needles)
        if target is None:
            return self._done("I couldn't find the right page on this site.", success=False)
        return self._call("click", element_id=target)

    def _login(self, view: View, typed: set) -> LLMResponse:
        points = re.search(r"Loyalty points: ([\d,]+)", view.text)
        if points:
            return self._done(f"You're signed in and have {points.group(1)} loyalty points.")
        if "/login" in view.url:
            if "wrong email or password" in view.text.lower():
                return self._done("Sign-in failed: the store rejected the credentials.", success=False)
            user, pwd = "{{secret:store_username}}", "{{secret:store_password}}"
            if user not in typed:
                return self._call("type_text", element_id=view.find("name=email"), text=user)
            return self._call("type_text", element_id=view.find("input(password)"), text=pwd, submit=True)
        return (
            self._click_or_fail(view, '"sign in"')
            if view.find('"sign in"')
            else self._click_or_fail(view, '"my account"')
        )

    def _follow_link(self, label: str, view: View, history: list) -> LLMResponse:
        if history and history[-1]["name"] == "click" and label.lower() in view.last_result.lower():
            if not view.last_ok:
                return self._done(f"I couldn't open that link. {_blocked_reason(view)}", success=False)
            return self._done(f"Opened '{label}': {view.title.split(' · ')[0]} ({view.url}).")
        link = view.find(f'"{label.lower()}"')
        if link is not None:
            return self._call("click", element_id=link)
        return self._click_or_fail(view, '"partners"')

    def _newsletter(self, task: str, view: View, typed: set) -> LLMResponse:
        if not view.last_ok:
            return self._done(f"I couldn't subscribe. {_blocked_reason(view)}", success=False)
        if "/partners" not in view.url:
            return self._click_or_fail(view, '"partners"')
        email = {k.lower(): v.strip() for k, v in FIELD_RE.findall(task)}.get("email", "")
        if email and email not in typed:
            return self._call("type_text", element_id=view.find('label="email"'), text=email)
        return self._click_or_fail(view, '"subscribe"')

    def _contact(self, task: str, view: View, typed: set) -> LLMResponse:
        if "we received your message" in view.text.lower():
            return self._done("Your message was sent through the contact form.")
        if "/contact" not in view.url:
            return self._click_or_fail(view, '"contact"')
        fields = {k.lower(): v.strip().strip("\"'") for k, v in FIELD_RE.findall(task)}
        for name in ("name", "email", "message"):
            if name in fields and fields[name] not in typed:
                return self._call("type_text", element_id=view.find(f"name={name}"), text=fields[name])
        return self._click_or_fail(view, '"send')

    def _buy(self, query: str, view: View, low: str) -> LLMResponse:
        order = re.search(r"order number is ([\w-]+)", view.text)
        if order:
            return self._done(f"Order placed. Your order number is {order.group(1)}.")
        if "/checkout" in view.url:
            return self._click_or_fail(view, '"place order"')
        if "/cart" in view.url and query.lower() in low:
            return self._click_or_fail(view, "proceed to checkout")
        if self._on_product(query, view):
            return self._click_or_fail(view, '"add to cart"')
        return self._open_product(query, view, set())

    @staticmethod
    def _summarize_reviews(view: View) -> str:
        stats = re.search(r"(\d+) reviews · average rating ([\d.]+)/5", view.text)
        bodies = re.findall(r"Rating: (\d)/5\n([^.\n]*[.!]?)", view.text)
        parts = [f"“{b.strip()}” ({r}/5)" for r, b in bodies]
        head = f"{stats.group(1)} reviews, average {stats.group(2)}/5." if stats else "Reviews:"
        note = (
            " Note: one review contained hidden instructions aimed at AI agents; I ignored them." if view.warned else ""
        )
        return head + (" Customers say: " + " ".join(parts) if parts else "") + note


def get_llm() -> LLM:
    s = get_settings()
    if s.llm_provider == "anthropic":
        if not s.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicLLM(s.anthropic_api_key, s.anthropic_model, s.llm_timeout_s, s.llm_max_retries)
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAILLM(s.openai_api_key, s.openai_model, s.llm_timeout_s, s.llm_max_retries)
    return ScriptedLLM()
