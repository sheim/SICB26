from schedule_tool import resolve_room_conflicts


def make_event(event_id: int, start_min: int, end_min: int) -> dict:
    return {
        "id": event_id,
        "start_min": start_min,
        "end_min": end_min,
    }


def test_keeps_longer_overlap() -> None:
    events = [
        make_event(1, 9 * 60, 10 * 60),
        make_event(2, 9 * 60 + 15, 9 * 60 + 45),
    ]
    resolved = resolve_room_conflicts(events)
    assert [event["id"] for event in resolved] == [1]


def test_longer_replaces_shorter_when_late() -> None:
    events = [
        make_event(1, 9 * 60, 10 * 60),
        make_event(2, 9 * 60 + 30, 11 * 60),
    ]
    resolved = resolve_room_conflicts(events)
    assert [event["id"] for event in resolved] == [2]


def test_non_overlapping_remains() -> None:
    events = [
        make_event(1, 9 * 60, 10 * 60),
        make_event(2, 10 * 60, 11 * 60),
    ]
    resolved = resolve_room_conflicts(events)
    assert [event["id"] for event in resolved] == [1, 2]
