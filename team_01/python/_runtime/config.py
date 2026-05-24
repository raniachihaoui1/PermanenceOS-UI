from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    api_key: str
    base_url: str
    llm_model: str
    request_timeout_seconds: float
    max_iterations: int


@dataclass(frozen=True)
class LLMOnlySettings:
    api_key: str
    base_url: str
    llm_model: str


def _repo_root() -> Path:
    # team_01/python/_runtime/config.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing or empty required environment variable: {name}")
    return value


def _provider_settings() -> tuple[str, str, str, str]:
    load_dotenv(dotenv_path=_repo_root() / ".env", override=False)

    provider = _required_env("LLM_PROVIDER").strip().lower()

    if provider == "local":
        api_key = "No API Key Required"
        base_url = _required_env("LOCAL_LLM_ENDPOINT")
        llm_model = _required_env("LOCAL_LLM_MODEL")

    elif provider == "cloudflare":
        api_key = _required_env("CF_API_TOKEN")
        account_id = _required_env("CF_ACCOUNT_ID")
        base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        llm_model = _required_env("CF_MODEL")

    elif provider == "openai":
        api_key = _required_env("OPENAI_API_KEY")
        base_url = "https://api.openai.com/v1"
        llm_model = _required_env("OPENAI_MODEL")

    elif provider == "google":
        api_key = _required_env("GOOGLE_API_KEY")
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        llm_model = _required_env("GOOGLE_MODEL")

    elif provider == "anthropic":
        api_key = _required_env("ANTHROPIC_API_KEY")
        base_url = "https://api.anthropic.com/v1/"
        llm_model = _required_env("ANTHROPIC_MODEL")

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")

    return provider, api_key, base_url, llm_model


def load_settings() -> Settings:
    provider, api_key, base_url, llm_model = _provider_settings()
    timeout_seconds = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))
    max_iterations = int(os.environ.get("MAX_ITERATIONS", "4"))

    return Settings(
        llm_provider=provider,
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model,
        request_timeout_seconds=timeout_seconds,
        max_iterations=max_iterations,
    )


def load_llm_only_settings() -> LLMOnlySettings:
    _, api_key, base_url, llm_model = _provider_settings()
    return LLMOnlySettings(api_key=api_key, base_url=base_url, llm_model=llm_model)
