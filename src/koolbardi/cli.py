from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import typer

from .config import load_config
from .pipeline import advance, finalize, initialize, run_worker
from .queue import TaskQueue

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
    phase: Literal["instruction", "response", "audit"] = typer.Option(...),
    once: bool = False,
) -> None:
    """Claim and process phase shards atomically until the queue is empty."""
    config, queue = context(config_path)
    typer.echo(f"processed={asyncio.run(run_worker(config, queue, phase, once))}")


@app.command()
def advance_queue(config_path: Path = typer.Argument(..., exists=True)) -> None:
    """Enqueue downstream shards whose atomic upstream files exist."""
    config, queue = context(config_path)
    typer.echo(f"added={advance(config, queue)}")


@app.command()
def status(config_path: Path = typer.Argument(..., exists=True)) -> None:
    config, queue = context(config_path)
    typer.echo(json.dumps(queue.status(), indent=2))


@app.command()
def reset_stale(config_path: Path = typer.Argument(..., exists=True), age_seconds: float = 3600) -> None:
    config, queue = context(config_path)
    typer.echo(f"reset={queue.reset_stale(age_seconds)}")


@app.command()
def finalize_dataset(
    config_path: Path = typer.Argument(..., exists=True),
    output: Path = typer.Option(..., "--output", "-o"),
) -> None:
    config, queue = context(config_path)
    del queue
    typer.echo(json.dumps(finalize(config, output), indent=2))

