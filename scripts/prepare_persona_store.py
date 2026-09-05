#!/usr/bin/env python3
"""Normalize English and Danish persona Parquet files into an indexed store."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pyarrow.parquet as pq


def clean(value, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit]


def without_name(value, name, limit: int = 500) -> str:
    text = clean(value, limit)
    full_name = clean(name, 160)
    for candidate in (full_name, full_name.split(" ", 1)[0] if full_name else ""):
        if candidate:
            text = text.replace(candidate, "personen")
    return text


def age_band(value) -> str:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return ""
    lower = max(0, age // 10 * 10)
    return f"{lower}-{lower + 9}"


def normalized(row: dict, language: str) -> dict:
    if language == "da":
        interests = without_name(row.get("hobbies_and_interests"), row.get("name"))
        profile = ""
        source = "oliverkinch/danish-personas"
    else:
        interests = clean(row.get("hobbies_and_interests_list") or row.get("hobbies_and_interests"))
        profile = clean(row.get("skills_and_expertise_list") or row.get("skills_and_expertise"))
        source = "nvidia/Nemotron-Personas-USA"
    return {
        "source": source,
        "age_band": age_band(row.get("age")),
        "occupation": clean(row.get("occupation"), 160),
        "education": clean(row.get("education_level"), 160),
        "interests": interests,
        "profile": profile,
    }


def ingest(connection: sqlite3.Connection, root: Path, language: str) -> int:
    position = 0
    for path in sorted(root.rglob("*.parquet")):
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=4096):
            records = []
            for row in batch.to_pylist():
                records.append((
                    language,
                    position,
                    str(row["uuid"]),
                    json.dumps(normalized(row, language), ensure_ascii=False, separators=(",", ":")),
                ))
                position += 1
            connection.executemany(
                "INSERT INTO personas(language, position, source_id, payload) VALUES (?, ?, ?, ?)",
                records,
            )
        connection.commit()
    return position


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--english-root", type=Path, required=True)
    parser.add_argument("--danish-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(temporary)
    connection.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE personas (
            language TEXT NOT NULL,
            position INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY(language, position)
        ) WITHOUT ROWID;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    counts = {
        "en": ingest(connection, args.english_root, "en"),
        "da": ingest(connection, args.danish_root, "da"),
    }
    connection.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        [(f"rows_{language}", str(count)) for language, count in counts.items()],
    )
    check = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    if check != "ok":
        raise RuntimeError(f"persona store integrity check failed: {check}")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "rows": counts}, indent=2))


if __name__ == "__main__":
    main()
