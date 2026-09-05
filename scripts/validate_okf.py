#!/usr/bin/env python3
"""Validate Koolbardi's Open Knowledge Format bundle."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
DATE_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}$", re.MULTILINE)
VALID_STATUS = {"draft", "stable", "deprecated"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def metadata(text: str) -> dict | None:
    match = FRONTMATTER.match(text)
    if not match:
        return None
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise ValueError("frontmatter must be a mapping")
    return value


def validate(bundle: Path) -> list[str]:
    bundle = bundle.resolve()
    errors: list[str] = []
    files = sorted(bundle.rglob("*.md"))
    for directory in {bundle, *(path.parent for path in files)}:
        index = directory / "index.md"
        if not index.is_file():
            errors.append(f"{directory.relative_to(bundle)}: missing index.md")
            continue
        targets = {
            target.split("#", 1)[0]
            for target in LINK.findall(index.read_text(encoding="utf-8"))
        }
        children = [
            path.name for path in directory.glob("*.md")
            if path.name not in {"index.md", "log.md"}
        ]
        children += [
            f"{path.name}/" for path in directory.iterdir()
            if path.is_dir() and any(path.rglob("*.md"))
        ]
        for child in children:
            if child not in targets:
                errors.append(f"{index.relative_to(bundle)}: missing link to {child}")

    for path in files:
        rel = path.relative_to(bundle)
        text = path.read_text(encoding="utf-8")
        try:
            meta = metadata(text)
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: invalid frontmatter: {exc}")
            continue
        if path.name == "index.md":
            if rel == Path("index.md") and str((meta or {}).get("okf_version")) != "0.2":
                errors.append("index.md: missing okf_version 0.2")
            elif rel != Path("index.md") and meta is not None:
                errors.append(f"{rel}: subdirectory index must not have frontmatter")
        elif path.name == "log.md":
            if meta is not None or not DATE_HEADING.search(text):
                errors.append(f"{rel}: invalid reserved log")
        else:
            if meta is None or not str(meta.get("type", "")).strip():
                errors.append(f"{rel}: missing concept type")
                continue
            if meta.get("status") not in VALID_STATUS:
                errors.append(f"{rel}: invalid status")
            if meta.get("confidence") not in VALID_CONFIDENCE:
                errors.append(f"{rel}: invalid confidence")
            if path.stat().st_size >= 50_000:
                errors.append(f"{rel}: concept exceeds 50,000 bytes")
        if "[[" in text or "]]" in text:
            errors.append(f"{rel}: legacy wiki-link syntax")
        for target in LINK.findall(text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or not target.endswith((".md", "/")):
                continue
            resolved = (bundle / target.lstrip("/")) if target.startswith("/") else (path.parent / target)
            if target.endswith("/"):
                resolved /= "index.md"
            if not resolved.resolve().exists():
                errors.append(f"{rel}: unresolved link {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", nargs="?", type=Path, default=Path("wiki"))
    errors = validate(parser.parse_args().bundle)
    for error in errors:
        print(f"error: {error}")
    print(f"OKF validation: {len(errors)} error(s)")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
