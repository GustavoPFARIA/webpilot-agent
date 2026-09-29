"""OpenTelemetry tracing: one span per run, with child spans for every LLM call
and browser action. LLM spans follow the GenAI semantic conventions
(gen_ai.request.model, gen_ai.usage.input_tokens, ...), so the traces render in
Jaeger, Grafana Tempo, Honeycomb, Datadog or Langfuse without custom mapping.

Tracing is a no-op until an exporter is configured:
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # any OTLP collector
  OTEL_CONSOLE=true                                   # print spans to stdout
"""

import os

from opentelemetry import trace

tracer = trace.get_tracer("webpilot")
_configured = False


def setup(console: bool = False) -> None:
    global _configured
    if _configured:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not (endpoint or console):
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "webpilot-agent"}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True
