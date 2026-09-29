# Observability

## Traces (OpenTelemetry)

Each run produces one trace:

```
webpilot.run                       task, model, status, steps, cost_usd
├── gen_ai.chat                    gen_ai.request.model, gen_ai.usage.input_tokens / output_tokens
├── webpilot.action.navigate       ok, outcome
├── gen_ai.chat
├── webpilot.action.click          ok, outcome  (e.g. "Blocked by network policy: ...")
└── ...
```

LLM spans use the OpenTelemetry **GenAI semantic conventions**, so Jaeger, Grafana Tempo, Honeycomb, Datadog and Langfuse show model, tokens and latency without custom mapping.

Tracing is a no-op until you configure an exporter:

```bash
# Any OTLP/HTTP collector (Jaeger, Tempo, an OTel Collector, Langfuse, ...)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn app.main:app

# Or print spans to the console
OTEL_CONSOLE=true uvicorn app.main:app
```

Quick local Jaeger:

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn app.main:app
# open http://localhost:16686
```

## Cost

Each run's `usage` includes `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `llm_calls` and `cost_usd`. The cost comes from `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK` and `PRICE_CACHE_READ_PER_MTOK`, so set them to your model's current prices. The UI shows tokens and cost per run. `MAX_COST_PER_RUN_USD` stops a run that goes over.

## Logs

Every step and every blocked request is logged:

```
INFO webpilot step 3 click {"element_id": 9} -> Clicked [9] Partner deals Blocked by network policy: http://evil.example/deals (...)
WARNING webpilot network policy blocked http://evil.example/deals: Blocked: 'evil.example' is not in the allowed domains (...)
```

Secret values never appear in logs. Actions are logged with their placeholders (`{{secret:store_password}}`), because substitution happens after logging, at the browser layer.

## Evals as a quality metric

`evals/results.md` records pass/fail, steps and time per case. Running the same dataset against different models (`LLM_PROVIDER=anthropic|openai`) compares pass rate, steps and tokens. See [evaluation.md](evaluation.md).
