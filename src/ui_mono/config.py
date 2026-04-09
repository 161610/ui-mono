from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv


CLAUDE_CODE_CONFIG_PATH = Path.home() / ".claude" / "config.json"
ANTHROPIC_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def load_env(cwd: Path) -> None:
    load_dotenv(cwd / ".env")
    load_dotenv()
    load_claude_code_env()


def load_claude_code_env() -> None:
    if not CLAUDE_CODE_CONFIG_PATH.exists():
        return
    try:
        data = json.loads(CLAUDE_CODE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    env = data.get("env")
    if not isinstance(env, dict):
        return

    for key in ANTHROPIC_ENV_KEYS:
        value = env.get(key)
        if isinstance(value, str) and value:
            os.environ.setdefault(key, value)


def get_anthropic_client_kwargs() -> dict[str, str]:
    kwargs: dict[str, str] = {}
    for key, field in (
        ("ANTHROPIC_API_KEY", "api_key"),
        ("ANTHROPIC_AUTH_TOKEN", "auth_token"),
        ("ANTHROPIC_BASE_URL", "base_url"),
    ):
        value = os.getenv(key)
        if value:
            kwargs[field] = value
    return kwargs


def has_anthropic_credentials() -> bool:
    kwargs = get_anthropic_client_kwargs()
    return bool(kwargs.get("api_key") or kwargs.get("auth_token"))


def get_agent_home() -> Path:
    return Path.home() / ".ui-mono"


def get_sessions_dir() -> Path:
    return get_agent_home() / "sessions"
