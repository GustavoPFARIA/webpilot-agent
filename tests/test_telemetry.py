"""The agent emits one span per run with child spans for LLM calls and actions."""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.agent import Agent
from app.browser.page_state import PageState
from tests.conftest import SHOP, FakeBrowser, ListLLM, call

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)


async def test_spans(settings):
    exporter.clear()
    llm = ListLLM([[call("navigate", url=SHOP)], [call("done", answer="ok", success=True)]])
    await Agent(llm, FakeBrowser({SHOP: PageState(url=SHOP)}), settings).run("x")

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert {"webpilot.run", "gen_ai.chat", "webpilot.action.navigate"} <= spans.keys()
    run = spans["webpilot.run"]
    assert run.attributes["webpilot.status"] == "done"
    assert spans["gen_ai.chat"].attributes["gen_ai.usage.input_tokens"] == 10
    assert spans["gen_ai.chat"].parent.span_id == run.context.span_id
