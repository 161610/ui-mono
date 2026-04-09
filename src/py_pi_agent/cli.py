from __future__ import annotations

from pathlib import Path

import typer

from py_pi_agent.agent_loop import AgentLoop
from py_pi_agent.app import build_registry
from py_pi_agent.config import (
    get_sessions_dir,
    has_anthropic_credentials,
    load_env,
)
from py_pi_agent.models.anthropic import AnthropicModelClient
from py_pi_agent.session.store import SessionStore

app = typer.Typer(add_completion=False)


@app.command()
def chat(
    cwd: str = typer.Option(".", help="Working directory"),
    resume: bool = typer.Option(False, help="Resume latest session"),
    model: str = typer.Option("claude-opus-4-6", help="Anthropic model id"),
) -> None:
    working_dir = Path(cwd).resolve()
    load_env(working_dir)
    if not has_anthropic_credentials():
        raise typer.BadParameter("Anthropic credentials are not set")

    session_store = SessionStore(get_sessions_dir())
    session_path = session_store.latest() if resume else None
    if session_path is None:
        session_path = session_store.create()

    history, summary = session_store.load_history(session_path)
    registry = build_registry(working_dir)
    model_client = AnthropicModelClient(model=model)
    agent_loop = AgentLoop(model_client, registry, session_store)

    typer.echo(f"session: {session_path}")
    typer.echo("Type /quit to exit")

    while True:
        user_input = typer.prompt("you")
        if user_input.strip() == "/quit":
            break
        reply, history, summary = agent_loop.run_turn(session_path, history, user_input, summary)
        if reply:
            typer.echo(f"assistant> {reply}")


if __name__ == "__main__":
    app()
