from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM provider: "auto" picks the first configured key (Anthropic, OpenAI,
    # Gemini). "scripted" is a deterministic offline policy for tests and CI only.
    llm_provider: str = "auto"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    # Any OpenAI-compatible server: Groq, OpenRouter, Ollama (http://localhost:11434/v1), vLLM...
    openai_base_url: str | None = None
    # Google Gemini has a free tier (no card): https://aistudio.google.com/apikey
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    # Minimum seconds between model calls, to stay under free-tier rate limits.
    # Unset = provider default (Gemini free tier: 6.5 s, others: none).
    llm_min_interval_s: float | None = None

    # Browser. BROWSER_CHANNEL=msedge/chrome uses an installed browser instead of
    # the bundled Chromium (handy on machines where the download is blocked).
    browser_channel: str | None = None
    headless: bool = True
    max_steps: int = 15
    approval_timeout_s: float = 300

    # Security policy: the agent may only open these hosts (and their subdomains).
    allowed_domains: list[str] = ["127.0.0.1", "localhost"]
    # Credentials the agent can use via {{secret:NAME}} placeholders. The model
    # only ever sees the placeholder. Defaults are the demo store's fake account.
    secrets: dict[str, str] = {"store_username": "demo@acme.test", "store_password": "demo-pass-8431"}

    # Paths the browser may never load, on any allowed host (this app's own API
    # and internals: the agent must not approve its own actions or read other runs).
    browser_denied_paths: list[str] = ["/api/", "/docs", "/redoc", "/openapi.json", "/health", "/sandbox/_state"]

    # Where this server is reachable; the demo store lives at {public_url}/sandbox.
    public_url: str = "http://127.0.0.1:8000"

    # API access. Maps bearer token -> user id. When empty, the API only accepts
    # requests from this machine (loopback), as user "local": secure by default.
    api_keys: dict[str, str] = {}

    # Abuse and cost limits (OWASP LLM10: unbounded consumption).
    runs_per_minute: int = 10
    max_concurrent_runs: int = 2  # per user
    run_timeout_s: float = 600
    max_tokens_per_run: int = 300_000
    max_cost_per_run_usd: float = 1.00
    # USD per million tokens, for cost tracking. Unset = the provider's default
    # model price (Gemini free tier = 0). Set them if you change models or plans.
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None
    price_cache_read_per_mtok: float | None = None

    # Resilience for model API calls (429 / 5xx / network): SDK retries with backoff.
    llm_timeout_s: float = 60
    llm_max_retries: int = 3

    # Observability: OpenTelemetry spans for runs, steps, LLM calls and actions.
    # Export with the standard OTEL_EXPORTER_OTLP_ENDPOINT, or print with OTEL_CONSOLE=true.
    otel_console: bool = False

    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        for provider, key in (
            ("anthropic", self.anthropic_api_key),
            ("openai", self.openai_api_key),
            ("gemini", self.gemini_api_key),
        ):
            if key:
                return provider
        return "scripted"

    def prices(self) -> tuple[float, float, float]:
        """(input, output, cache read) in USD per million tokens."""
        default = DEFAULT_PRICES.get(self.resolved_provider(), (0.0, 0.0, 0.0))
        chosen = (self.price_input_per_mtok, self.price_output_per_mtok, self.price_cache_read_per_mtok)
        return (
            chosen[0] if chosen[0] is not None else default[0],
            chosen[1] if chosen[1] is not None else default[1],
            chosen[2] if chosen[2] is not None else default[2],
        )


# List prices of each provider's default model (USD / 1M tokens: input, output, cache read).
DEFAULT_PRICES = {
    "anthropic": (3.00, 15.00, 0.30),
    "openai": (0.40, 1.60, 0.10),
    "gemini": (0.0, 0.0, 0.0),  # free tier
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
