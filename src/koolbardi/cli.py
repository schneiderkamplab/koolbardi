from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import typer

from .config import load_config
from .pipeline import advance, finalize, initialize, run_worker
from .queue import TaskQueue
from .selection import select_audit_tasks, select_response_tasks

app = typer.Typer(no_args_is_help=True, help="Bilingual Magpie-style data generation.")


def context(config_path: Path):
    config = load_config(config_path)
    queue = TaskQueue(config.root / "queue.sqlite3")
    return config, queue


@app.command()
def init(config_path: Path = typer.Argument(..., exists=True)) -> None:
    """Initialize idempotent instruction-generation shards."""
    config, queue = context(config_path)
    config.root.mkdir(parents=True, exist_ok=True)
    receipt = config.root / "config.receipt.json"
    receipt.write_text(config.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(f"added={initialize(config, queue)} config_hash={config.receipt_hash()}")


@app.command()
def work(
    config_path: Path = typer.Argument(..., exists=True),
    phase: Literal["instruction", "instruction_audit", "response", "audit"] = typer.Option(...),
    once: bool = False,
) -> None:
    """Claim and process phase shards atomically until the queue is empty."""
    config, queue = context(config_path)
    processed = asyncio.run(run_worker(config, queue, phase, once)
    )
    failed = queue.count(phase, "failed")
    typer.echo(f"processed={processed} failed={failed}")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def advance_queue(config_path: Path = typer.Argument(..., exists=True)) -> None:
    """Enqueue downstream shards whose atomic upstream files exist."""
    config, queue = context(config_path)
    typer.echo(f"added={advance(config, queue)}")


@app.command()
def select_responses(config_path: Path = typer.Argument(..., exists=True)) -> None:
    """Select a balanced, extensible subset of pending response shards."""
    config, queue = context(config_path)
    result = select_response_tasks(config, queue)
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "selected_shard_keys"}, indent=2))


@app.command()
def select_audits(config_path: Path = typer.Argument(..., exists=True)) -> None:
    """Select buffered audit shards for exact balanced final targets."""
    config, queue = context(config_path)
    result = select_audit_tasks(config, queue)
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "selected_shard_keys"}, indent=2))


@app.command()
def status(config_path: Path = typer.Argument(..., exists=True)) -> None:
    config, queue = context(config_path)
    typer.echo(json.dumps(queue.status(), indent=2))


@app.command()
def reset_stale(config_path: Path = typer.Argument(..., exists=True), age_seconds: float = 3600) -> None:
    config, queue = context(config_path)
    typer.echo(f"reset={queue.reset_stale(age_seconds)}")


@app.command()
def reset_failed(
    config_path: Path = typer.Argument(..., exists=True),
    phase: Literal["instruction", "instruction_audit", "response", "audit"] | None = typer.Option(None),
) -> None:
    """Reset terminal failures after their underlying cause has been corrected."""
    config, queue = context(config_path)
    typer.echo(f"reset={queue.reset_failed(phase)}")


@app.command()
def finalize_dataset(
    config_path: Path = typer.Argument(..., exists=True),
    output: Path = typer.Option(..., "--output", "-o"),
) -> None:
    config, queue = context(config_path)
    del queue
    typer.echo(json.dumps(finalize(config, output), indent=2))
