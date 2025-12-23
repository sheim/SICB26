"""Helpers for reading and applying GUI layout overrides."""

from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_DISPLAY_OPTIONS = {
    "show_session": True,
    "show_talk_title": True,
    "show_time": True,
    "show_room": True,
}

DEFAULT_TITLE_MAX_LENGTH = 60

DEFAULT_LAYOUT = {
    "room_order_by_day": {},
    "hidden_event_ids_by_day": {},
    "misc_rooms_by_day": {},
    "display_options": DEFAULT_DISPLAY_OPTIONS,
    "title_max_length": DEFAULT_TITLE_MAX_LENGTH,
}


def normalize_layout(data: dict | None) -> dict:
    layout = copy.deepcopy(DEFAULT_LAYOUT)
    if not isinstance(data, dict):
        return layout

    room_order = data.get("room_order_by_day")
    if isinstance(room_order, dict):
        for day, rooms in room_order.items():
            if isinstance(rooms, list):
                normalized = [str(room) for room in rooms if room]
                if normalized:
                    layout["room_order_by_day"][str(day)] = normalized

    hidden = data.get("hidden_event_ids_by_day")
    if isinstance(hidden, dict):
        for day, ids in hidden.items():
            if isinstance(ids, list):
                normalized = []
                for item in ids:
                    try:
                        normalized.append(int(item))
                    except (TypeError, ValueError):
                        continue
                if normalized:
                    layout["hidden_event_ids_by_day"][str(day)] = normalized

    misc_rooms = data.get("misc_rooms_by_day")
    if isinstance(misc_rooms, dict):
        for day, rooms in misc_rooms.items():
            if isinstance(rooms, list):
                normalized = [str(room) for room in rooms if room]
                if normalized:
                    layout["misc_rooms_by_day"][str(day)] = normalized

    display_options = data.get("display_options")
    if isinstance(display_options, dict):
        for key in DEFAULT_DISPLAY_OPTIONS:
            value = display_options.get(key)
            if isinstance(value, bool):
                layout["display_options"][key] = value

    title_max_length = data.get("title_max_length")
    if title_max_length is not None:
        try:
            layout["title_max_length"] = max(0, int(title_max_length))
        except (TypeError, ValueError):
            pass

    return layout


def load_layout(path: Path) -> dict:
    if not path.exists():
        return copy.deepcopy(DEFAULT_LAYOUT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return copy.deepcopy(DEFAULT_LAYOUT)
    return normalize_layout(data)


def save_layout(path: Path, layout: dict) -> None:
    normalized = normalize_layout(layout)
    path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def apply_layout(
    events: list[dict], day_name: str, layout: dict
) -> tuple[list[dict], list[str], list[str]]:
    hidden_ids = set(layout.get("hidden_event_ids_by_day", {}).get(day_name, []))
    filtered = [event for event in events if event.get("id") not in hidden_ids]
    room_order = layout.get("room_order_by_day", {}).get(day_name, [])
    misc_rooms = layout.get("misc_rooms_by_day", {}).get(day_name, [])
    return filtered, room_order, misc_rooms


def get_display_settings(layout: dict | None) -> tuple[dict, int]:
    display = copy.deepcopy(DEFAULT_DISPLAY_OPTIONS)
    title_max_length = DEFAULT_TITLE_MAX_LENGTH
    if layout:
        display.update(layout.get("display_options", {}))
        title_max_length = layout.get("title_max_length", title_max_length)
    return display, title_max_length
