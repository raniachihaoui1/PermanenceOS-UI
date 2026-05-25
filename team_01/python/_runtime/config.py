from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    llm_model: str
    request_timeout_seconds: float
    max_iterations: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_settings() -> Settings:
    load_dotenv(dotenv_path=_repo_root() / ".env", override=False)
    base_url = os.environ.get("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:1234/v1/")
    llm_model = os.environ.get("LOCAL_LLM_MODEL", "meta-llama-3.1-8b-instruct")
    timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "60"))
    max_iter = int(os.environ.get("MAX_ITERATIONS", "20"))
    return Settings(
        api_key="no-key-needed",
        base_url=base_url,
        llm_model=llm_model,
        request_timeout_seconds=timeout,
        max_iterations=max_iter,
    )
