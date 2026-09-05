#!/usr/bin/env python3
"""Freeze a diversity report after one percent of each language lane is generated."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from koolbardi.config import load_config


def read_rows(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def normalized_prefix(text: str, words: int = 6) -> str:
    tokens = re.findall(r"\w+", text.casefold())
    return " ".join(tokens[:words])


def entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total < 1 or len(counter) < 2:
        return 0.0
    value = -sum((count / total) * math.log(count / total) for count in counter.values())
    return value / math.log(len(counter))


def first_user(row: dict) -> str:
    if "instruction" in row:
        return row["instruction"]
    return row["messages"][0]["content"]


def lane_report(rows: list[dict], language: str, sample_output: Path) -> dict:
    lane = [row for row in rows if row["language_lane"] == language]
    sample = sorted(
        lane,
        key=lambda row: hashlib.sha256(
            f"controlled-diversity-1pct:{row['id']}".encode()
        ).digest(),
    )[:100]
    with sample_output.open("a", encoding="utf-8") as handle:
        for row in sample:
            handle.write(json.dumps({
                "id": row["id"],
                "language": language,
                "diversity": row.get("diversity"),
                "first_user": first_user(row),
            }, ensure_ascii=False) + "\n")
    topics = Counter(row["diversity"]["topic_id"] for row in lane)
    domains = Counter(row["diversity"]["topic_domain"] for row in lane)
    modes = Counter(row["diversity"]["interaction_mode"] for row in lane)
    personas = Counter(row["diversity"]["persona_source_id"] for row in lane)
    prefixes = Counter(normalized_prefix(first_user(row)) for row in sample)
    texts = [first_user(row) for row in sample]
    matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1).fit_transform(texts)
    similarities = cosine_similarity(matrix)
    near = {}
    for threshold in (0.65, 0.75, 0.85):
        pairs = sum(
            similarities[left, right] >= threshold
            for left in range(len(sample)) for right in range(left + 1, len(sample))
        )
        members = {
            index for index in range(len(sample))
            if any(index != other and similarities[index, other] >= threshold for other in range(len(sample)))
        }
        near[str(threshold)] = {"pairs": int(pairs), "rows_with_neighbor": len(members)}
    return {
        "rows": len(lane),
        "topics": {"unique": len(topics), "normalized_entropy": entropy(topics), "top": topics.most_common(10)},
        "domains": {"unique": len(domains), "normalized_entropy": entropy(domains), "counts": dict(domains)},
        "modes": {"unique": len(modes), "normalized_entropy": entropy(modes), "top": modes.most_common(10)},
        "personas": {"unique": len(personas), "maximum_reuse": max(personas.values())},
        "sample_prefixes": prefixes.most_common(10),
        "sample_near_duplicates": near,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--fraction", type=float, default=0.01)
    parser.add_argument("--phase", choices=("instruction", "response"), default="instruction")
    parser.add_argument("--poll-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    thresholds = {
        lane.language: math.ceil(lane.accepted_target * args.fraction)
        for lane in config.lanes
    }
    while True:
        rows = read_rows(config.root / args.phase)
        counts = Counter(row["language_lane"] for row in rows)
        print(json.dumps({"counts": counts, "thresholds": thresholds}), flush=True)
        if all(counts[language] >= target for language, target in thresholds.items()):
            break
        time.sleep(args.poll_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sample_output = args.output.with_suffix(".sample.jsonl")
    sample_output.unlink(missing_ok=True)
    report = {
        "config": str(args.config),
        "config_hash": config.receipt_hash(),
        "fraction": args.fraction,
        "phase": args.phase,
        "created_at": int(time.time()),
        "lanes": {
            language: lane_report(rows, language, sample_output)
            for language in thresholds
        },
    }
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
