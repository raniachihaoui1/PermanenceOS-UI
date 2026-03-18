from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    debug_graph: bool
    mcp_config_path: str
    mcp_server_key: str
    mcp_endpoint: str
    request_timeout_seconds: float
    max_iterations: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing or empty required environment variable: {name}")
    return value


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False

    raise ValueError(f"Invalid value for {name}: {raw_value}. Allowed values are 'true' or 'false'.")


def _validate_openai_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OPENAI_BASE_URL must be a valid http/https URL")

    if not parsed.path.rstrip("/").endswith("/v1"):
        raise ValueError("OPENAI_BASE_URL must include '/v1' for OpenAI-compatible Chat Completions")

    return base_url


def _load_mcp_server_from_json(config_path: Path) -> tuple[str, str]:
    if not config_path.exists():
        raise ValueError(f"MCP config file not found: {config_path}")

    raw = config_path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"MCP config file is empty: {config_path}")

    parsed = json.loads(raw)

    if "mcpServers" not in parsed:
        raise ValueError("mcp.json missing 'mcpServers' object")

    servers = parsed["mcpServers"]
    if not isinstance(servers, dict) or not servers:
        raise ValueError("mcp.json 'mcpServers' must be a non-empty object")

    server_key = next(iter(servers))
    server_config = servers[server_key]
    if not isinstance(server_config, dict):
        raise ValueError(f"mcp.json server entry must be an object: {server_key}")

    endpoint: str | None = None

    if "url" in server_config:
        url_value = server_config["url"]
        if not isinstance(url_value, str) or not url_value:
            raise ValueError("mcp.json server 'url' must be a non-empty string")
        endpoint = url_value
    elif "args" in server_config:
        args_value = server_config["args"]
        if not isinstance(args_value, list) or not args_value:
            raise ValueError("mcp.json server 'args' must be a non-empty array")
        first_arg = args_value[0]
        if not isinstance(first_arg, str) or not first_arg:
            raise ValueError("mcp.json server args[0] must be a non-empty string endpoint")
        endpoint = first_arg
    else:
        raise ValueError(
            "mcp.json server entry missing supported endpoint field. Expected 'url' or 'args[0]'."
        )

    return server_key, endpoint


def load_settings() -> Settings:
    load_dotenv(dotenv_path=_repo_root() / ".env", override=False)

    mcp_json_path = _repo_root() / "mcp.json"
    mcp_server_key, mcp_endpoint = _load_mcp_server_from_json(mcp_json_path)

    timeout_value = os.environ.get("REQUEST_TIMEOUT_SECONDS", "30")
    max_iterations_value = os.environ.get("MAX_ITERATIONS", "4")

    return Settings(
        openai_api_key=_required_env("OPENAI_API_KEY"),
        openai_base_url=_validate_openai_base_url(_required_env("OPENAI_BASE_URL")),
        openai_model=_required_env("OPENAI_MODEL"),
        debug_graph=_parse_bool_env("DEBUG_GRAPH", False),
        mcp_config_path=str(mcp_json_path),
        mcp_server_key=mcp_server_key,
        mcp_endpoint=mcp_endpoint,
        request_timeout_seconds=float(timeout_value),
        max_iterations=int(max_iterations_value),
    )
