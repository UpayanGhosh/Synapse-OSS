#!/usr/bin/env python3
"""Substitute metric placeholders in README.md from docs/_generated/metrics.json.

Placeholders are HTML comments of the form ``<!--METRIC:key-->`` followed by an
existing value (any text up to the next whitespace or angle bracket). The
script regenerates the value in-place so it is safe to run repeatedly.

Exits 0 silently when README.md or metrics.json is missing, or when no
placeholders exist. No external dependencies; stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
METRICS_PATH = REPO_ROOT / "docs" / "_generated" / "metrics.json"

# Matches `<!--METRIC:key-->` optionally followed by a previously rendered value
# (everything up to the next whitespace or `<`). The trailing value is captured
# so we can replace it with the fresh metric.
PLACEHOLDER_RE = re.compile(
    r"(<!--METRIC:(?P<key>[a-zA-Z0-9_]+)-->)(?P<value>[^\s<]*)"
)


def main() -> int:
    if not README_PATH.exists():
        return 0
    if not METRICS_PATH.exists():
        return 0

    try:
        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    original = README_PATH.read_text(encoding="utf-8")
    if "<!--METRIC:" not in original:
        return 0

    def _sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if key not in metrics:
            return match.group(0)
        return f"{match.group(1)}{metrics[key]}"

    rendered = PLACEHOLDER_RE.sub(_sub, original)

    if rendered != original:
        README_PATH.write_text(rendered, encoding="utf-8")
        print(f"Updated {README_PATH.relative_to(REPO_ROOT)}")
    else:
        print("README.md already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
