from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from dateutil import parser as date_parser

SOURCE = Path(__file__).resolve().parents[2] / "workspace" / "sci_fi_dashboard" / "pipeline_helpers.py"
NAMES = {
    "ParsedReminder",
    "_REMINDER_TRIGGERS",
    "_DURATION_RE",
    "_RELATIVE_BEFORE_RE",
    "_NO_ARTICLE_EVENTS",
    "_duration_from_match",
    "_event_article",
    "_is_reminder_request",
    "_extract_event_name",
    "_extract_reminder_task",
    "_parse_reminder_request",
}


def load_production_parser():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id in NAMES
            for target in (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, ast.AnnAssign)
                else [ast.Name(id=node.name)]
            )
        )
    ]
    namespace = {
        "re": re,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "UTC": UTC,
        "date_parser": date_parser,
        "dataclass": dataclass,
    }
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace["_parse_reminder_request"]


def test_time_only_reminder_that_passed_rolls_to_tomorrow_not_next_year() -> None:
    parse = load_production_parser()
    base = datetime(2026, 9, 22, 14, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    parsed = parse("Remind me at 9am to call the dentist", now=base)

    assert parsed is not None
    assert parsed.when == datetime(2026, 9, 23, 9, 0, tzinfo=base.tzinfo)


def test_weekday_reminder_resolves_to_next_matching_weekday() -> None:
    parse = load_production_parser()
    base = datetime(2026, 9, 20, 14, 0, tzinfo=UTC)  # Sunday

    parsed = parse("Remind me Saturday at 9am to buy flowers", now=base)

    assert parsed is not None
    assert parsed.when == datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
