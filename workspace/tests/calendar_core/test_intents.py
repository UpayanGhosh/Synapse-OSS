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


# ---------------------------------------------------------------------------
# V2 intent tests
# ---------------------------------------------------------------------------


def test_affirmation_yes_classifies_independently_of_other_keywords():
    for phrase in ("yes", "Yep", "go ahead", "do it", "confirm", "sure", "okay"):
        intent = parse_calendar_intent(phrase, base_date=BASE)
        assert intent.kind == "affirm_yes", phrase


def test_negation_classifies_as_affirm_no():
    for phrase in ("no", "cancel", "nope", "stop", "never mind"):
        intent = parse_calendar_intent(phrase, base_date=BASE)
        assert intent.kind == "affirm_no", phrase


def test_quick_add_extracts_text_after_prefix():
    intent = parse_calendar_intent("quick add: lunch with Aman thursday 1pm", base_date=BASE)
    assert intent.kind == "quick_add"
    assert intent.quick_add is not None
    assert intent.quick_add.text == "lunch with Aman thursday 1pm"


def test_delete_event_intent():
    intent = parse_calendar_intent("delete the 4 PM standup", base_date=BASE)
    assert intent.kind == "delete_event"
    assert "standup" in intent.target_query.lower()


def test_cancel_meeting_intent_classifies_as_delete():
    intent = parse_calendar_intent("cancel my dentist appointment", base_date=BASE)
    assert intent.kind == "delete_event"
    assert "dentist" in intent.target_query.lower()


def test_move_event_intent_parses_new_time():
    intent = parse_calendar_intent(
        "move tomorrow's call to Friday at 5 pm",
        base_date=BASE,
    )
    assert intent.kind == "move_event"
    assert intent.new_start.startswith("2026-05-08T17:00:00")
    assert intent.new_end.startswith("2026-05-08T18:00:00")


def test_reschedule_event_intent_parses_new_time():
    intent = parse_calendar_intent("reschedule the standup to tomorrow at 9 am", base_date=BASE)
    assert intent.kind == "move_event"
    assert intent.new_start.startswith("2026-05-06T09:00:00")


def test_update_event_intent_with_title_change():
    intent = parse_calendar_intent("rename the standup to morning sync", base_date=BASE)
    assert intent.kind == "update_event"
    assert intent.new_title == "morning sync"


def test_rsvp_yes_intent():
    intent = parse_calendar_intent("RSVP yes to the budget review", base_date=BASE)
    assert intent.kind == "rsvp"
    assert intent.rsvp_response == "accepted"
    assert "budget review" in intent.target_query.lower()


def test_rsvp_no_intent():
    intent = parse_calendar_intent("decline tomorrow's standup", base_date=BASE)
    assert intent.kind == "rsvp"
    assert intent.rsvp_response == "declined"


def test_rsvp_tentative_intent():
    intent = parse_calendar_intent("rsvp maybe to the all-hands", base_date=BASE)
    assert intent.kind == "rsvp"
    assert intent.rsvp_response == "tentative"


def test_freebusy_multi_calendar_intent():
    intent = parse_calendar_intent(
        "Am I free Friday afternoon across both calendars?",
        base_date=BASE,
    )
    assert intent.kind == "freebusy"
    assert intent.freebusy is not None
    assert intent.freebusy.calendar_ids == ["primary"]


def test_unrelated_yes_in_middle_of_sentence_is_not_affirmation():
    intent = parse_calendar_intent(
        "Add yes-meeting tomorrow at 3 pm",
        base_date=BASE,
    )
    assert intent.kind == "create_event"
