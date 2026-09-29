from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM: "scripted" runs a deterministic offline policy (demo, CI, evals).
    llm_provider: str = "scripted"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"

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

    # Where this server is reachable; the demo store lives at {public_url}/sandbox.
    public_url: str = "http://127.0.0.1:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
