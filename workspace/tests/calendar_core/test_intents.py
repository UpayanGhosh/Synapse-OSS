from __future__ import annotations

from datetime import date

from sci_fi_dashboard.calendar_core.intents import parse_calendar_intent


BASE = date(2026, 5, 5)


def test_parse_gym_daily_recurring_create():
    intent = parse_calendar_intent("Add gym every day at 7 PM starting tomorrow", base_date=BASE)
    assert intent.kind == "create_event"
    assert intent.create.title.lower() == "gym"
    assert intent.create.start == "2026-05-06T19:00:00+05:30"
    assert intent.create.end == "2026-05-06T20:00:00+05:30"
    assert intent.create.recurrence is not None
    assert intent.create.recurrence.frequency == "daily"


def test_parse_birthday_as_yearly_all_day():
    intent = parse_calendar_intent("Remember Arjun's birthday on July 12 every year", base_date=BASE)
    assert intent.kind == "create_event"
    assert intent.create.title == "Arjun's birthday"
    assert intent.create.start == "2026-07-12"
    assert intent.create.end == "2026-07-13"
    assert intent.create.all_day is True
    assert intent.create.recurrence is not None
    assert intent.create.recurrence.frequency == "yearly"


def test_parse_availability_question():
    intent = parse_calendar_intent("Am I free Friday afternoon?", base_date=BASE)
    assert intent.kind == "availability"
    assert intent.availability.start == "2026-05-08T12:00:00+05:30"
    assert intent.availability.end == "2026-05-08T17:00:00+05:30"


def test_parse_holiday_question():
    intent = parse_calendar_intent("When is Independence Day holiday?", base_date=BASE)
    assert intent.kind == "holiday"
    assert "Independence Day" in intent.query


def test_parse_list_calendar_question():
    intent = parse_calendar_intent("What meetings do I have tomorrow?", base_date=BASE)
    assert intent.kind == "list_events"
    assert intent.availability.start == "2026-05-06T00:00:00+05:30"
    assert intent.availability.end == "2026-05-07T00:00:00+05:30"
