"""Helpers for reading and applying GUI layout overrides."""

from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_LAYOUT = {
    "room_order_by_day": {},
    "hidden_event_ids_by_day": {},
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


def apply_layout(events: list[dict], day_name: str, layout: dict) -> tuple[list[dict], list[str]]:
    hidden_ids = set(layout.get("hidden_event_ids_by_day", {}).get(day_name, []))
    filtered = [event for event in events if event.get("id") not in hidden_ids]
    room_order = layout.get("room_order_by_day", {}).get(day_name, [])
    return filtered, room_order
