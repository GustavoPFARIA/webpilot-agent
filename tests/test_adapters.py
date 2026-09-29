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
    return llm


def test_openai_parses_function_calls_and_ignores_custom_ones():
    calls = [
        NS(type="function", id="c1", function=NS(name="click", arguments='{"element_id": 3}')),
        NS(type="custom", id="c2", custom=NS(name="x", input="free text")),
    ]
    resp = _openai(_openai_response(calls)).complete(["s"], MESSAGES, TOOLS)
    assert resp.tool_calls == [{"type": "tool_use", "id": "c1", "name": "click", "input": {"element_id": 3}}]
    assert resp.usage == {"input_tokens": 50, "output_tokens": 7, "cache_read_input_tokens": 40}


def test_openai_survives_missing_usage_and_malformed_arguments():
    calls = [NS(type="function", id="c1", function=NS(name="click", arguments='{"element_id": '))]
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
