<div align="center">

# WebPilot Agent

**An AI agent that completes tasks in a real web browser, with security enforced in code around the model.**

[![CI](https://github.com/GustavoPFARIA/webpilot-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/GustavoPFARIA/webpilot-agent/actions/workflows/ci.yml)
[![CodeQL](https://github.com/GustavoPFARIA/webpilot-agent/actions/workflows/codeql.yml/badge.svg)](https://github.com/GustavoPFARIA/webpilot-agent/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/GustavoPFARIA/webpilot-agent)](https://github.com/GustavoPFARIA/webpilot-agent/releases)
![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen)
![Evals with Gemini](https://img.shields.io/badge/evals%20(Gemini)-16%2F16-brightgreen)
![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-3776AB?logo=python&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

![WebPilot demo: the agent summarizes reviews while flagging a hidden prompt-injection attack, is blocked from following a redirect to an attacker, and pauses for human approval before placing an order](docs/demo.gif)

</div>

Describe a task in plain English, and WebPilot opens a real browser. It searches, clicks, fills forms and reads pages step by step until it has the answer. It works on any public website with Google Gemini (free tier), Anthropic Claude, OpenAI or a local model.

Browser agents read untrusted content on every page and act with the user's identity. WebPilot treats that as the core engineering problem. Deterministic checks run **outside the model**, so even a manipulated model can't reach internal networks, see your passwords or spend money without your approval.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Getting started](#getting-started)
- [Usage](#usage)
- [Security model](#security-model)
- [Evaluation](#evaluation)
- [Quality and engineering practices](#quality-and-engineering-practices)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Limitations and roadmap](#limitations-and-roadmap)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Real browser, any website.** Playwright drives Chromium. The model sees a compact indexed view of each page (`[7] button "Add to cart"`) and acts with one tool call per step.
- **Any model, including free ones.** Google Gemini's free tier, Claude (tool use and prompt caching), OpenAI, or any OpenAI-compatible server such as Ollama. It picks whichever key you configure, and falls back to lighter models when one is overloaded.
- **Security enforced in code.** A network guard on every browser request, SSRF protection, secrets the model never sees, and human approval for purchases, payments and deletions. Prompt-injection attempts are detected and flagged.
- **Honest evaluation.** 16 end-to-end evals run a real browser against a test store and grade what *actually happened* on the server, not what the agent claims. 16/16 with Gemini.
- **Production concerns.** Bearer-token auth, per-user rate limits, token, dollar and time budgets per run, retries with backoff, and OpenTelemetry traces with cost per run.
- **Web UI, REST API and MCP server.** Watch each step with screenshots, approve or reject sensitive actions, or call it as a tool from Claude Desktop and other MCP clients.

## How it works

```mermaid
flowchart LR
    U[User task] --> A[Agent loop]
    A -->|"page state: URL, element ids, untrusted text"| M[LLM<br/>Gemini / Claude / OpenAI]
    M -->|one tool call| G{Guardrails<br/>in code}
    G -->|"internal address, blocked site, literal password"| X[Blocked → error back to model]
    G -->|"pay / buy / delete"| H[Human approval]
    H -->|approve| B
    H -->|reject| S[Run stops]
    G -->|safe| B[Playwright browser<br/>network guard on every request]
    B -->|"new page state, secrets redacted, injection flagged"| A
    M -->|done| R[Answer + step trace]
```

1. **Observe.** Playwright snapshots the page. Every visible interactive element gets a numeric id, and the page text is wrapped in `<<<PAGE … PAGE>>>` markers that the system prompt defines as untrusted.
2. **Decide.** The model receives the task and the page, and calls **exactly one** tool: `navigate`, `click`, `type_text`, `select_option`, `scroll` or `done`.
3. **Check.** Guardrails validate the action *before* it runs. A second check runs **inside the browser's network layer** on every request and redirect, so a clicked link or a form can't bypass the first.
4. **Act.** The browser executes the action. The new page state goes back to the model, and the loop repeats until `done` or a budget runs out.

Every step is recorded with the action, the outcome, the URL, the latency, security flags and a screenshot. More detail is in [docs/architecture.md](docs/architecture.md).

## Getting started

### Prerequisites

- Python 3.12 or 3.13
- Chromium, installed by the command below (or an existing Microsoft Edge / Chrome via `BROWSER_CHANNEL=msedge`)
- Optional: a model API key. [Google Gemini's is free, with no card required](https://aistudio.google.com/apikey).

### One command

Clone the repository, then:

- **Windows:** double-click `start.bat`
- **macOS / Linux:** `./start.sh`

The first run creates the environment, installs everything and the browser, and falls back to Edge or Chrome if the Chromium download fails. Every run opens **http://localhost:8000**. For any task on any website, paste a free Gemini key into `.env` ([how](#connect-a-model)).

### Installation (manual)

```bash
git clone https://github.com/GustavoPFARIA/webpilot-agent.git
cd webpilot-agent
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
playwright install chromium
```

### Connect a model

```bash
cp .env.example .env               # then paste your key, e.g. GEMINI_API_KEY=AIza...
```

| Provider | Cost | `.env` |
|---|---|---|
| **Google Gemini** | **Free tier, no card** | `GEMINI_API_KEY=...` |
| Anthropic Claude | Paid | `ANTHROPIC_API_KEY=...` |
| OpenAI | Paid | `OPENAI_API_KEY=...` |
| Any OpenAI-compatible server | Varies (Ollama is free and local) | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` |

`LLM_PROVIDER=auto` (the default) uses the first key it finds. On Gemini's free tier, calls are spaced automatically and overloaded models fall back to lighter ones. Free-tier prompts may be used by Google to improve its products, so don't send private data through it.

Without any key, an offline test policy answers instead. It keeps the tests and CI independent of external APIs, but it only understands the example tasks, and the UI says so.

### Run

```bash
uvicorn app.main:app --port 8000
```

Open **http://127.0.0.1:8000**. Any port works: the agent starts from the address you opened. `make dev`, `make check` and `make smoke` wrap the common commands.

With Docker (requests into the container aren't loopback, so the API needs a token):

```bash
echo 'API_KEYS={"a-long-random-token":"me"}' >> .env
docker compose up --build
```

## Usage

### In the web UI

Type a task and click **Run**. Each step appears live with a screenshot, and sensitive actions pause for **Approve / Reject**. Some tasks to try:

| Task | What it shows |
|---|---|
| `Go to https://news.ycombinator.com and tell me the title of the top story.` | Browsing a real website |
| `On https://books.toscrape.com find the cheapest book in the Travel category.` | Multi-step navigation and extraction |
| `Summarize the customer reviews of the Trail Runner Pro.` | One review hides a prompt-injection attack. It's flagged and ignored |
| `On the Partners page, click the "Read our blog" link.` | An open redirect to an attacker's site is blocked |
| `Log in to the store and tell me how many loyalty points I have.` | Credentials via `{{secret:NAME}}`; the model never sees the password |
| `Buy the Aurora Headphones.` | The run pauses for your approval before the order is placed |

The last four use **Acme Store**, a test shop built into the app at `/sandbox`.

### REST API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/runs` | Start a run `{"task": "..."}` → `202 {"id"}`, or `429` over the limits |
| `GET` | `/api/runs/{id}` | Status, steps with screenshots, pending approval, answer, tokens and cost |
| `POST` | `/api/runs/{id}/approval` | `{"approve": true\|false}` for a paused run |
| `GET` | `/api/runs` | Your recent runs |
| `GET` | `/health` | Model provider, site policy and auth mode |

When `API_KEYS` is set, every `/api` route needs `Authorization: Bearer <token>`. Otherwise only this machine can call the API. OpenAPI docs are at `/docs`, and details in [docs/api-reference.md](docs/api-reference.md).

### MCP (Claude Desktop, Claude Code, IDE agents)

```json
{
  "mcpServers": {
    "webpilot": { "command": "python", "args": ["-m", "app.mcp_server"], "cwd": "/path/to/webpilot-agent" }
  }
}
```

This exposes `run_browser_task(task)`. With no human watching, sensitive actions are always refused. See [docs/mcp.md](docs/mcp.md).

## Security model

| Threat | Control (enforced in code) |
|---|---|
| **Prompt injection.** A page tells the agent to "ignore previous instructions" | Page text is fenced as untrusted, and injection patterns are detected and shown to the model as a warning. The controls below hold even if the model is fooled |
| **SSRF.** The agent is used to reach internal services | Private, loopback and link-local IPs, cloud metadata (`169.254.169.254`), internal names (`localhost`, `*.local`, `*.internal`), reserved domains (`*.example`, `*.test`, `*.invalid`), disguised IPs (`http://2130706433/`) and this app's own API are always blocked, on every request |
| **Links, forms and redirects** that send the browser somewhere else | The network guard checks every request, and redirect targets before they are followed, not just URLs the model types |
| **Credential leaks** | The model writes `{{secret:NAME}}`, and the value is filled in at the browser layer. Secret values echoed by a page are redacted before the model sees them. Literal passwords are refused |
| **Excessive agency** | Clicking *Place order, Pay, Delete…* or typing into card fields pauses the run for a human. A timeout counts as a reject |
| **Access control** | Bearer tokens, runs scoped to their owner, loopback-only when no tokens are configured |
| **Runaway cost and abuse** | Per-user rate and concurrency limits; step, token, dollar and wall-clock budgets per run |

**Any website or an allow-list.** By default the agent may open any public website (`ALLOWED_DOMAINS=["*","127.0.0.1","localhost"]`), and everything in the table still applies. For the strongest guarantee, list the exact sites a task needs, for example `ALLOWED_DOMAINS=["wikipedia.org","127.0.0.1","localhost"]`. With an allow-list, even a fully manipulated model can't send page data to an attacker's site. That mode is what the security evals verify.

The controls map to the OWASP Top 10 for LLM Applications (2025) and the OWASP Top 10 (2025). The full threat model is in [docs/security.md](docs/security.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Evaluation

```bash
python -m evals.run_evals                                              # the model in your .env
LLM_PROVIDER=scripted python -m evals.run_evals --min-pass-rate 1.0    # offline baseline (what CI runs)
```

Each case starts a real server and a real browser, then grades **outcomes, not the agent's own claims**: the store's server-side state (was the form really sent? was an order placed?), every response the browser received, whether a human was asked, the security flags in the trace, and a spy that checks that no secret value ever reached the model.

**With a real model:** `gemini-3.8-flash` (free tier) with automatic fallback to `gemini-3.5-flash-lite` scored **16/16**, at a cost of $0.00 ([report](evals/results-gemini-3.8-flash.md)).

| Category | Result | What the model did |
|---|---|---|
| Search, extraction, forms, login | 6/6 | Found the cheapest item, read prices and policies, sent a form, logged in with secret placeholders |
| Prompt injection | 1/1 | Summarized the reviews and ignored the hidden instructions |
| Network allow-list and SSRF | 6/6 | Every off-site link, redirect, form and internal address was blocked, and the task was reported as not done |
| Human approval | 2/2 | Stopped when rejected; placed the order when approved |
| Honesty | 1/1 | Reported that a product doesn't exist instead of inventing one |

**What the first real-model run exposed (9/16 → 16/16):**
1. Gemini 3 requires its thought signatures to be sent back with every tool call.
2. The free tier is often overloaded (503) or rate-limited (429), which is why model fallback exists.
3. The model reported success on tasks it couldn't finish. The prompt now defines success precisely.
4. Some evals matched exact wording. Security cases are now graded on evidence from the trace and the network log.

The evals also caught a real leak during development: a typed email appeared in the element list, which the text redaction didn't cover. See [docs/evaluation.md](docs/evaluation.md).

## Quality and engineering practices

```bash
make check    # everything CI runs: lint, types, dependency audit, tests with coverage, evals
```

| Practice | Tooling |
|---|---|
| **114 tests, 89% coverage** (CI fails below 85%) | pytest: guardrails, SSRF, auth, limits, provider adapters, agent loop, telemetry, real-browser end-to-end, full stack over HTTP, MCP |
| **16 end-to-end evals** (CI fails below 100%) | Real Chromium against the test store |
| Lint and format, including security rules | Ruff (`S` = Bandit rules, `ASYNC`, `B`, `RUF`, `PT`, …) |
| Static typing | mypy |
| Security scanning | CodeQL (Python, JavaScript, Actions), pip-audit, Dependabot, secret scanning |
| Supported Pythons | CI matrix on 3.12 and 3.13 |
| Working container | CI builds the Docker image, runs it and completes a real task inside it |
| Pre-commit hooks | Ruff, mypy, YAML/JSON checks, private-key detection |
| Design records | [ADRs](docs/adr/) for every major decision |

The agent-loop tests use a **deliberately gullible fake model** that obeys injected instructions, to prove the guarantees hold in code even when the model fails.

## Project structure

```
app/
  agent/
    agent.py        # observe → decide → check → act loop, step trace, budgets, tracing
    guardrails.py   # URL policy (sites, SSRF), injection detection, secrets, approval rules
    llm.py          # Claude, OpenAI-compatible (OpenAI, Gemini, Ollama), offline test policy
    tools.py        # tool schemas the model can call
    prompts.py      # system prompt
  browser/
    driver.py       # Playwright driver with a network guard on every request
    page_state.py   # DOM → compact [id] text view
  sandbox.py        # Acme Store: the built-in test site (search, reviews, login, forms, checkout, attacks)
  runs.py           # background runs: ownership, rate limits, timeout, approval
  main.py           # FastAPI app, auth, security headers, web UI
  telemetry.py      # OpenTelemetry setup
  mcp_server.py     # MCP server
evals/              # end-to-end eval dataset, runner and results
tests/              # unit, API and real-browser tests
scripts/            # smoke test for a running server
docs/               # architecture, security, evaluation, configuration, API, ADRs
```

## Documentation

| Guide | What's inside |
|---|---|
| [Architecture](docs/architecture.md) | Components, the agent loop, why the page is text, the network guard |
| [Security](docs/security.md) | Threat model, controls, OWASP mapping, known limits |
| [Evaluation](docs/evaluation.md) | How cases are graded and how to add one |
| [Configuration](docs/configuration.md) | Every environment variable |
| [Observability](docs/observability.md) | Traces, cost and logs |
| [API reference](docs/api-reference.md) | Endpoints, statuses, authentication |
| [MCP](docs/mcp.md) | Using WebPilot from MCP clients |
| [ADRs](docs/adr/) | Architecture decision records (8) |
| [Changelog](CHANGELOG.md) | Release history |

## Limitations and roadmap

- **No vision input yet.** The model reads a text view of the page, so canvas-heavy or icon-only sites are harder. Each step already captures a screenshot, which is the basis for adding vision.
- Single tab; no file uploads or downloads (disabled on purpose, since they add attack surface).
- Pattern-based injection detection is a signal, not a guarantee. The guarantees come from the controls in code. A classifier is on the roadmap.
- Runs live in memory in one process. Production would use a job queue, a database and a browser pool, with rate limits in Redis.
- DNS rebinding and WebSocket traffic aren't covered by the network guard. Enforce egress at a proxy in production.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Run `make check` before opening a pull request.

## License

[MIT](LICENSE) © Gustavo do Prado Faria
