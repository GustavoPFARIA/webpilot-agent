"""The real provider adapters, with the SDK clients replaced by fakes: request
shape (prompt caching, tools) and response parsing (tool calls, usage)."""

from types import SimpleNamespace as NS

import pytest

from app import telemetry
from app.agent.llm import AnthropicLLM, OpenAILLM, _parse_args, get_llm
from app.agent.tools import TOOLS
from app.config import get_settings

MESSAGES = [{"role": "user", "content": "Task: x"}]


class Block(NS):
    def model_dump(self, include):
        return {k: v for k, v in vars(self).items() if k in include}


def test_anthropic_request_uses_prompt_caching_and_parses_tool_calls():
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return NS(
            content=[
                Block(type="thinking", thinking="..."),  # dropped: not part of the protocol
                Block(type="text", text="Opening the store."),
                Block(type="tool_use", id="tu_1", name="navigate", input={"url": "http://127.0.0.1/"}),
            ],
            usage=NS(input_tokens=120, output_tokens=30, cache_read_input_tokens=None),
        )

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.client, llm.model, llm.name = NS(messages=NS(create=create)), "claude-x", "claude-x"
    resp = llm.complete(["system prompt"], MESSAGES, TOOLS)

    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["tools"] == TOOLS and sent["model"] == "claude-x"
    assert resp.text == "Opening the store."
    assert resp.tool_calls == [
        {"type": "tool_use", "id": "tu_1", "name": "navigate", "input": {"url": "http://127.0.0.1/"}}
    ]
    assert resp.usage == {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 0}


def _openai_response(tool_calls, usage=True):
    return NS(
        choices=[NS(message=NS(content=None, tool_calls=tool_calls))],
        usage=NS(prompt_tokens=50, completion_tokens=7, prompt_tokens_details=NS(cached_tokens=40)) if usage else None,
    )


def _openai(response):
    llm = OpenAILLM.__new__(OpenAILLM)
    llm.client = NS(chat=NS(completions=NS(create=lambda **_: response)))
    llm.model = llm.name = "gpt-x"
    llm.min_interval_s = 0.0
    llm.fallback_models, llm.cooldown_s, llm._cooldown_until = [], 120.0, {}
    return llm


def test_openai_parses_function_calls_and_ignores_custom_ones():
    calls = [
        NS(type="function", id="c1", function=NS(name="click", arguments='{"element_id": 3}'), model_extra={}),
        NS(type="custom", id="c2", custom=NS(name="x", input="free text")),
    ]
    resp = _openai(_openai_response(calls)).complete(["s"], MESSAGES, TOOLS)
    assert resp.tool_calls == [{"type": "tool_use", "id": "c1", "name": "click", "input": {"element_id": 3}}]
    assert resp.usage == {"input_tokens": 50, "output_tokens": 7, "cache_read_input_tokens": 40, "model": "gpt-x"}


def test_openai_survives_missing_usage_and_malformed_arguments():
    calls = [NS(type="function", id="c1", function=NS(name="click", arguments='{"element_id": '), model_extra={})]
    resp = _openai(_openai_response(calls, usage=False)).complete(["s"], MESSAGES, TOOLS)
    assert resp.tool_calls[0]["input"] == {}
    assert resp.usage["input_tokens"] == 0


@pytest.mark.parametrize(("raw", "expected"), [(None, {}), ("[1]", {}), ("oops", {}), ('{"a": 1}', {"a": 1})])
def test_parse_args(raw, expected):
    assert _parse_args(raw) == expected


def test_provider_selection(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_llm()
    monkeypatch.setattr(s, "llm_provider", "openai")
    monkeypatch.setattr(s, "openai_api_key", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_llm()
    monkeypatch.setattr(s, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(s, "llm_provider", "anthropic")
    llm = get_llm()
    assert isinstance(llm, AnthropicLLM)
    assert llm.client.max_retries == s.llm_max_retries


def test_telemetry_is_off_without_an_exporter(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry, "_configured", False)
    telemetry.setup(console=False)
    assert telemetry._configured is False


def test_auto_provider_picks_the_first_configured_key():
    from app.config import Settings

    assert Settings(_env_file=None, llm_provider="auto").resolved_provider() == "scripted"
    assert Settings(_env_file=None, llm_provider="auto", gemini_api_key="g").resolved_provider() == "gemini"
    both = Settings(_env_file=None, llm_provider="auto", gemini_api_key="g", anthropic_api_key="a")
    assert both.resolved_provider() == "anthropic"


def test_prices_default_per_provider_and_can_be_overridden():
    from app.config import Settings

    assert Settings(_env_file=None, llm_provider="gemini").prices() == (0.0, 0.0, 0.0)  # free tier
    assert Settings(_env_file=None, llm_provider="anthropic").prices() == (3.0, 15.0, 0.3)
    custom = Settings(_env_file=None, llm_provider="gemini", price_input_per_mtok=0.3, price_output_per_mtok=2.5)
    assert custom.prices() == (0.3, 2.5, 0.0)


def test_gemini_uses_the_openai_compatible_endpoint_with_throttling(monkeypatch):
    from app.agent.llm import GEMINI_BASE_URL

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "AIza-test")
    llm = get_llm()
    assert isinstance(llm, OpenAILLM)
    assert str(llm.client.base_url) == GEMINI_BASE_URL
    assert llm.min_interval_s == 6.5
    assert llm.fallback_models == s.gemini_fallback_models  # overloaded free models fall back to lighter ones


def test_throttle_spaces_out_calls(monkeypatch):
    import app.agent.llm as mod

    sleeps: list[float] = []
    clock = iter([100.0, 100.0, 101.0, 107.5])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(mod.time, "sleep", sleeps.append)
    llm = _openai(_openai_response([]))
    llm.min_interval_s, llm._last_call, llm._lock = 6.5, 0.0, mod.threading.Lock()
    llm._throttle()  # first call: no wait
    llm._throttle()  # 1 s later: waits the remaining 5.5 s
    assert sleeps == [5.5]


def _status_error(cls, code):
    import httpx

    req = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return cls("overloaded", response=httpx.Response(code, request=req), body=None)


def test_falls_back_when_the_primary_model_is_overloaded():
    import openai

    tried = []

    def create(model, **_):
        tried.append(model)
        if model == "big":
            raise _status_error(openai.InternalServerError, 503)
        return _openai_response(
            [NS(type="function", id="c1", function=NS(name="scroll", arguments="{}"), model_extra={})]
        )

    llm = _openai(None)
    llm.client = NS(chat=NS(completions=NS(create=create)))
    llm.model, llm.fallback_models, llm.cooldown_s, llm._cooldown_until = "big", ["lite"], 120.0, {}

    first = llm.complete(["s"], MESSAGES, TOOLS)
    assert tried == ["big", "lite"] and first.usage["model"] == "lite"
    llm.complete(["s"], MESSAGES, TOOLS)  # the overloaded model is skipped while cooling down
    assert tried == ["big", "lite", "lite"]


def test_errors_surface_when_every_model_fails():
    import openai

    def create(model, **_):
        raise _status_error(openai.RateLimitError, 429)

    llm = _openai(None)
    llm.client = NS(chat=NS(completions=NS(create=create)))
    llm.model, llm.fallback_models, llm.cooldown_s, llm._cooldown_until = "a", ["b"], 120.0, {}
    with pytest.raises(openai.RateLimitError):
        llm.complete(["s"], MESSAGES, TOOLS)


def test_bad_request_does_not_trigger_fallback():
    import openai

    tried = []

    def create(model, **_):
        tried.append(model)
        raise _status_error(openai.BadRequestError, 400)

    llm = _openai(None)
    llm.client = NS(chat=NS(completions=NS(create=create)))
    llm.model, llm.fallback_models, llm.cooldown_s, llm._cooldown_until = "a", ["b"], 120.0, {}
    with pytest.raises(openai.BadRequestError):
        llm.complete(["s"], MESSAGES, TOOLS)
    assert tried == ["a"]  # a bad request is our bug, not an outage: don't hide it


def test_gemini_thought_signatures_round_trip_and_never_reach_claude():
    from app.agent.llm import _strip_provider_extra

    sig = {"google": {"thought_signature": "abc"}}
    call = NS(type="function", id="c1", function=NS(name="scroll", arguments="{}"), model_extra={"extra_content": sig})
    resp = _openai(_openai_response([call])).complete(["s"], MESSAGES, TOOLS)
    assert resp.tool_calls[0]["provider_extra"] == sig

    history = [*MESSAGES, {"role": "assistant", "content": resp.content}]
    out, _ = OpenAILLM.to_openai(["s"], history, TOOLS)
    assert out[-1]["tool_calls"][0]["extra_content"] == sig  # sent back to Gemini
    assert "provider_extra" not in _strip_provider_extra(history)[-1]["content"][0]  # but not to Claude
