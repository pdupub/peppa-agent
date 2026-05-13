from __future__ import annotations

import asyncio
import shutil

import typer
import uvicorn

from peppa.config import ConfigError, load_settings
from peppa.core import Agent
from peppa.memory import Storage
from peppa.paths import (
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH,
    DATABASE_PATH,
    ROOT_DIR,
    ensure_runtime_dirs,
)


app = typer.Typer(help="Peppa local agent runtime.")


@app.command()
def init_config(force: bool = typer.Option(False, help="Overwrite existing config.toml.")) -> None:
    """Create a local config.toml from config.example.toml."""
    if CONFIG_PATH.exists() and not force:
        typer.echo(f"Config already exists: {CONFIG_PATH}")
        return
    if not CONFIG_EXAMPLE_PATH.exists():
        raise typer.BadParameter(f"Missing example config: {CONFIG_EXAMPLE_PATH}")
    shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
    typer.echo(f"Created {CONFIG_PATH}")


@app.command()
def reset_agent() -> None:
    """Reset Peppa's long-term local state."""
    if not DATABASE_PATH.exists():
        ensure_runtime_dirs()
        Storage().initialize()
        typer.echo(f"Created database: {DATABASE_PATH}")
        return

    confirmed = typer.confirm(
        f"This will delete Peppa's conversations, traces, and future memories at "
        f"{DATABASE_PATH}. Continue?"
    )
    if not confirmed:
        typer.echo("Reset cancelled. Existing agent state was kept.")
        return

    for path in (
        DATABASE_PATH,
        DATABASE_PATH.with_name(f"{DATABASE_PATH.name}-wal"),
        DATABASE_PATH.with_name(f"{DATABASE_PATH.name}-shm"),
    ):
        if path.exists():
            path.unlink()

    ensure_runtime_dirs()
    Storage().initialize()
    typer.echo(f"Reset agent state and initialized database: {DATABASE_PATH}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    reload: bool = typer.Option(False, help="Enable auto-reload for development."),
) -> None:
    """Start the local API server and debug console."""
    ensure_runtime_dirs()
    Storage().initialize()
    typer.echo(f"Starting Peppa from {ROOT_DIR}")
    typer.echo(f"Debug console: http://{host}:{port}")
    uvicorn.run("peppa.api.app:app", host=host, port=port, reload=reload)


@app.command()
def chat(
    message: str = typer.Argument(..., help="Message to send."),
    model: str | None = typer.Option(None, help="Configured model to use."),
) -> None:
    """Send a single CLI message through the same agent path."""
    result = asyncio.run(_chat_once(message=message, model=model))
    trace = result.trace
    if trace.error:
        typer.echo(f"Error: {trace.error}")
        raise typer.Exit(code=1)
    typer.echo(trace.assistant_message or "")


@app.command()
def models() -> None:
    """List configured models without exposing API keys."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}")
        raise typer.Exit(code=1) from exc

    for model in settings.models:
        marker = "*" if model.model == settings.default_model else " "
        typer.echo(f"{marker} {model.model} ({model.base_url})")


async def _chat_once(message: str, model: str | None) -> object:
    try:
        settings = load_settings()
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}")
        raise typer.Exit(code=1) from exc

    storage = Storage()
    storage.initialize()
    agent = Agent(settings=settings, storage=storage)
    return await agent.chat(user_message=message, requested_model=model)


if __name__ == "__main__":
    app()
