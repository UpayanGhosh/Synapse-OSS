from datetime import date

from sci_fi_dashboard.calendar_core.date_math import resolve_date_phrase


BASE = date(2026, 5, 5)  # Tuesday


def test_resolves_next_tuesday_as_following_week():
    result = resolve_date_phrase("next Tuesday", base_date=BASE)
    assert result.date.isoformat() == "2026-05-12"
    assert result.confidence >= 0.8


def test_resolves_tomorrow_afternoon_range():
    result = resolve_date_phrase("tomorrow afternoon", base_date=BASE)
    assert result.date.isoformat() == "2026-05-06"
    assert result.start.isoformat().startswith("2026-05-06T12:00:00")
    assert result.end.isoformat().startswith("2026-05-06T17:00:00")


def test_resolves_first_friday_of_june():
    result = resolve_date_phrase("first Friday of June", base_date=BASE)
    assert result.date.isoformat() == "2026-06-05"


def test_resolves_relative_day_words():
    assert resolve_date_phrase("today", base_date=BASE).date == date(2026, 5, 5)
    assert resolve_date_phrase("tomorrow", base_date=BASE).date == date(2026, 5, 6)
    assert resolve_date_phrase("yesterday", base_date=BASE).date == date(2026, 5, 4)


def test_resolves_plain_weekday_to_upcoming_day():
    assert resolve_date_phrase("Tuesday", base_date=BASE).date == date(2026, 5, 5)
    assert resolve_date_phrase("Friday", base_date=BASE).date == date(2026, 5, 8)
    assert resolve_date_phrase("Monday", base_date=BASE).date == date(2026, 5, 11)


def test_resolves_daypart_ranges():
    cases = [
        ("morning", "09:00:00", "12:00:00"),
        ("afternoon", "12:00:00", "17:00:00"),
        ("evening", "17:00:00", "21:00:00"),
        ("night", "21:00:00", "23:59:00"),
    ]
    for phrase, start_time, end_time in cases:
        result = resolve_date_phrase(f"today {phrase}", base_date=BASE)
        assert result.start.isoformat() == f"2026-05-05T{start_time}"
        assert result.end.isoformat() == f"2026-05-05T{end_time}"


def test_resolves_ordinal_weekday_of_month():
    assert resolve_date_phrase("first Friday of May", base_date=BASE).date == date(2027, 5, 7)
    assert resolve_date_phrase("second Monday of May", base_date=BASE).date == date(2026, 5, 11)
    assert resolve_date_phrase("third Wednesday of July", base_date=BASE).date == date(2026, 7, 15)
    assert resolve_date_phrase("fourth Thursday of August", base_date=BASE).date == date(2026, 8, 27)
    assert resolve_date_phrase("last Sunday of May", base_date=BASE).date == date(2026, 5, 31)


def test_resolves_iso_dates_and_month_day_phrases():
    assert resolve_date_phrase("2026-12-25", base_date=BASE).date == date(2026, 12, 25)
    assert resolve_date_phrase("June 3", base_date=BASE).date == date(2026, 6, 3)
    assert resolve_date_phrase("Jan 2nd", base_date=BASE).date == date(2027, 1, 2)


def test_unrecognized_phrase_returns_zero_confidence():
    result = resolve_date_phrase("someday after the big thing", base_date=BASE)
    assert result.date is None
    assert result.start is None
    assert result.end is None
    assert result.confidence == 0.0
    assert result.source == "unrecognized"
