"""The documented setup path must work: `cp .env.example .env` and start."""

from pathlib import Path

from app.config import Settings

EXAMPLE = Path(__file__).parents[1] / ".env.example"


def test_env_example_loads_with_defaults():
    s = Settings(_env_file=EXAMPLE)
    assert s.allowed_domains == ["*", "127.0.0.1", "localhost"]
    assert s.price_input_per_mtok is None and s.llm_min_interval_s is None  # blank lines mean "default"
    assert s.resolved_provider() in {"scripted", "gemini", "anthropic", "openai"}
