#!/usr/bin/env python3
"""Render room-by-time matrix PDFs directly from the SQLite database."""

from __future__ import annotations

import argparse
import collections
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF

import layout_config
from schedule_tool import (
    DAY_ORDER,
    load_events_by_day,
    minutes_to_label,
    resolve_room_conflicts,
    select_day_label,
)


@dataclass
class RenderConfig:
    page_size: str
    orientation: str
    slot_minutes: int
    margin: float
    header_height: float
    time_col_width: float
    header_font_size: float
    body_font_size: float
    padding: float


def sanitize_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": "\"",
        "\u201d": "\"",
        "\u2026": "...",
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def assign_misc_lanes(events: list[dict]) -> list[list[dict]]:
    lanes: list[list[dict]] = []
    for event in sorted(events, key=lambda e: (e["start_min"], e["end_min"])):
        placed = False
        for lane in lanes:
            if event["start_min"] >= lane[-1]["end_min"]:
                lane.append(event)
                placed = True
                break
        if not placed:
            lanes.append([event])
    return lanes


def wrap_text(pdf: FPDF, text: str, max_width: float) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.get_string_width(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if pdf.get_string_width(word) <= max_width:
            current = word
            continue
        chunk = ""
        for char in word:
            test = chunk + char
            if pdf.get_string_width(test) <= max_width:
                chunk = test
            else:
                if chunk:
                    lines.append(chunk)
                chunk = char
        current = chunk
    if current:
        lines.append(current)
    return lines


def shorten_line(pdf: FPDF, text: str, max_width: float, suffix: str = "...") -> str:
    if pdf.get_string_width(text) <= max_width:
        return text
    trimmed = text
    while trimmed and pdf.get_string_width(trimmed + suffix) > max_width:
        trimmed = trimmed[:-1]
    if not trimmed:
        return suffix
    return trimmed.rstrip() + suffix


def truncate_lines(
    pdf: FPDF, lines: list[str], max_width: float, max_lines: int
) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    trimmed = lines[:max_lines]
    trimmed[-1] = shorten_line(pdf, trimmed[-1], max_width)
    return trimmed


def draw_cell(
    pdf: FPDF,
    x: float,
    y: float,
    width: float,
    height: float,
    lines: list[str],
    fill_color: tuple[int, int, int] | None,
    align: str = "L",
    bold: bool = False,
    font_size: float | None = None,
    padding: float = 1.0,
) -> None:
    if fill_color:
        pdf.set_fill_color(*fill_color)
        pdf.rect(x, y, width, height, style="DF")
    else:
        pdf.rect(x, y, width, height)

    if not lines:
        return

    style = "B" if bold else ""
    if font_size is not None:
        pdf.set_font("Helvetica", style=style, size=font_size)
    else:
        pdf.set_font("Helvetica", style=style)
    line_height = pdf.font_size * 1.2
    max_lines = max(1, int((height - 2 * padding) / line_height))
    text_lines = truncate_lines(pdf, lines, width - 2 * padding, max_lines)
    cursor_y = y + padding
    for line in text_lines:
        pdf.set_xy(x + padding, cursor_y)
        pdf.cell(width - 2 * padding, line_height, line, align=align)
        cursor_y += line_height


def build_event_lines(pdf: FPDF, event: dict, max_width: float) -> list[str]:
    title_value = sanitize_text(event.get("title") or "(Untitled)")
    lines = wrap_text(pdf, title_value, max_width)
    details: list[str] = []
    misc_room = sanitize_text(event.get("_misc_source_room"))
    if misc_room:
        details.append(f"Room: {misc_room}")
    session = sanitize_text(event.get("session"))
    if session and session != title_value:
        details.append(session)
    talk_title = sanitize_text(event.get("talk_title"))
    if talk_title and talk_title != title_value and talk_title not in details:
        details.append(talk_title)
    conflicts = event.get("conflicts_ignored", 0)
    if conflicts:
        details.append(f"Overlap ignored ({conflicts})")
    for detail in details:
        lines.extend(wrap_text(pdf, detail, max_width))
    return lines


def render_day(
    pdf: FPDF,
    day_name: str,
    day_label: str,
    events: list[dict],
    config: RenderConfig,
    room_order_override: list[str] | None = None,
    misc_rooms_override: list[str] | None = None,
) -> None:
    events = [
        event
        for event in events
        if event.get("start_min") is not None and event.get("end_min") is not None
    ]
    if not events:
        return

    misc_rooms_set = set(misc_rooms_override or [])
    room_counts: collections.Counter[str] = collections.Counter()
    events_by_room: dict[str, list[dict]] = {}
    misc_by_room: dict[str, list[dict]] = {}
    for event in events:
        room = event.get("room") or "TBD"
        if room in misc_rooms_set:
            misc_by_room.setdefault(room, []).append(event)
        else:
            room_counts[room] += 1
            events_by_room.setdefault(room, []).append(event)

    default_rooms = sorted(room_counts.keys(), key=lambda r: (-room_counts[r], r))
    room_order_override = room_order_override or []
    seen_rooms: set[str] = set()
    rooms: list[str] = []
    for room in room_order_override:
        if room in room_counts and room not in seen_rooms:
            rooms.append(room)
            seen_rooms.add(room)
    for room in default_rooms:
        if room not in seen_rooms:
            rooms.append(room)
            seen_rooms.add(room)

    for room, room_events in list(events_by_room.items()):
        events_by_room[room] = resolve_room_conflicts(room_events)

    misc_events: list[dict] = []
    for room, room_events in misc_by_room.items():
        for event in resolve_room_conflicts(room_events):
            event["_misc_source_room"] = room
            misc_events.append(event)

    misc_lanes = assign_misc_lanes(misc_events)
    for idx, lane in enumerate(misc_lanes):
        label = "Misc" if idx == 0 else f"Misc {idx + 1}"
        rooms.append(label)
        events_by_room[label] = lane

    all_events = [event for room in rooms for event in events_by_room.get(room, [])]
    if not all_events:
        return

    day_start = min(event["start_min"] for event in all_events)
    day_end = max(event["end_min"] for event in all_events)
    slot_minutes = config.slot_minutes
    day_start = (day_start // slot_minutes) * slot_minutes
    if day_end % slot_minutes:
        day_end = ((day_end + slot_minutes - 1) // slot_minutes) * slot_minutes
    time_slots = list(range(day_start, day_end, slot_minutes))

    room_starts: dict[str, dict[int, dict]] = {room: {} for room in rooms}
    room_skips: dict[str, set[int]] = {room: set() for room in rooms}
    for room in rooms:
        for event in events_by_room.get(room, []):
            duration = max(1, event["end_min"] - event["start_min"])
            row_span = max(1, int((duration + slot_minutes - 1) // slot_minutes))
            event["_rowspan"] = row_span
            start = event["start_min"]
            room_starts[room][start] = event
            for offset in range(1, row_span):
                room_skips[room].add(start + offset * slot_minutes)

    pdf.add_page()
    pdf.set_auto_page_break(auto=False, margin=0)

    pdf.set_font("Helvetica", style="B", size=14)
    pdf.set_xy(config.margin, config.margin)
    pdf.cell(0, 6, sanitize_text(day_name), ln=1)
    pdf.set_font("Helvetica", size=9)
    pdf.set_x(config.margin)
    pdf.cell(0, 5, sanitize_text(day_label), ln=1)

    table_x = config.margin
    table_y = config.margin + config.header_height
    table_width = pdf.w - 2 * config.margin
    table_height = pdf.h - config.margin - table_y

    time_col_width = config.time_col_width
    room_col_width = (table_width - time_col_width) / max(1, len(rooms))

    pdf.set_font("Helvetica", size=config.header_font_size)
    header_line_height = pdf.font_size * 1.2
    header_padding = config.padding
    header_lines = 1
    for room in rooms:
        room_lines = wrap_text(
            pdf,
            sanitize_text(room),
            room_col_width - 2 * header_padding,
        )
        header_lines = max(header_lines, len(room_lines))
    header_height = max(
        header_line_height * header_lines + 2 * header_padding,
        header_line_height + 2 * header_padding,
    )

    body_height = max(1.0, table_height - header_height)
    row_height = body_height / max(1, len(time_slots))

    grid_color = (180, 170, 160)
    pdf.set_draw_color(*grid_color)
    pdf.set_line_width(0.1)

    header_fill = (236, 230, 219)
    draw_cell(
        pdf,
        table_x,
        table_y,
        time_col_width,
        header_height,
        ["Time"],
        header_fill,
        align="C",
        bold=True,
        font_size=config.header_font_size,
        padding=header_padding,
    )

    for idx, room in enumerate(rooms):
        cell_x = table_x + time_col_width + idx * room_col_width
        lines = wrap_text(
            pdf,
            sanitize_text(room),
            room_col_width - 2 * header_padding,
        )
        draw_cell(
            pdf,
            cell_x,
            table_y,
            room_col_width,
            header_height,
            lines,
            header_fill,
            align="C",
            bold=True,
            font_size=config.header_font_size,
            padding=header_padding,
        )

    body_y = table_y + header_height
    pdf.set_font("Helvetica", size=config.body_font_size)
    body_line_height = pdf.font_size * 1.2

    time_fill = (244, 239, 231)
    empty_fill = (250, 248, 243)
    event_fill = (255, 253, 247)

    for row_index, slot in enumerate(time_slots):
        row_y = body_y + row_index * row_height
        time_label = minutes_to_label(slot)
        time_bold = slot % 60 == 0
        draw_cell(
            pdf,
            table_x,
            row_y,
            time_col_width,
            row_height,
            [time_label],
            time_fill,
            align="C",
            bold=time_bold,
            font_size=config.body_font_size,
            padding=config.padding,
        )

        for idx, room in enumerate(rooms):
            if slot in room_skips.get(room, set()):
                continue
            cell_x = table_x + time_col_width + idx * room_col_width
            if slot in room_starts.get(room, {}):
                event = room_starts[room][slot]
                row_span = event.get("_rowspan", 1)
                cell_height = row_height * row_span
                lines = build_event_lines(
                    pdf, event, room_col_width - 2 * config.padding
                )
                draw_cell(
                    pdf,
                    cell_x,
                    row_y,
                    room_col_width,
                    cell_height,
                    lines,
                    event_fill,
                    align="L",
                    bold=False,
                    font_size=config.body_font_size,
                    padding=config.padding,
                )
            else:
                draw_cell(
                    pdf,
                    cell_x,
                    row_y,
                    room_col_width,
                    row_height,
                    [],
                    empty_fill,
                    align="L",
                    bold=False,
                    font_size=config.body_font_size,
                    padding=config.padding,
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a room-by-time matrix PDF directly from schedule.db."
    )
    parser.add_argument("--db", type=Path, default=Path("schedule.db"))
    parser.add_argument("--outdir", type=Path, default=Path("output-pdf"))
    parser.add_argument("--page-size", default="A4")
    parser.add_argument(
        "--orientation", choices=["portrait", "landscape"], default="landscape"
    )
    parser.add_argument("--slot-minutes", type=int, default=15)
    parser.add_argument("--font-size", type=float, default=6.5)
    parser.add_argument(
        "--layout",
        type=Path,
        default=Path("layout.json"),
        help="Layout overrides JSON",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    events_by_day = load_events_by_day(conn)
    layout = layout_config.load_layout(args.layout)

    config = RenderConfig(
        page_size=args.page_size,
        orientation=args.orientation,
        slot_minutes=args.slot_minutes,
        margin=8.0,
        header_height=16.0,
        time_col_width=24.0,
        header_font_size=7.0,
        body_font_size=float(args.font_size),
        padding=1.2,
    )

    args.outdir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for day_name in DAY_ORDER:
        events = events_by_day.get(day_name, [])
        if not events:
            continue
        events, room_order, misc_rooms = layout_config.apply_layout(
            events, day_name, layout
        )
        if not events:
            continue
        label = select_day_label(events)
        pdf = FPDF(
            orientation=args.orientation[0].upper(),
            unit="mm",
            format=args.page_size,
        )
        render_day(
            pdf,
            day_name,
            label,
            events,
            config,
            room_order_override=room_order,
            misc_rooms_override=misc_rooms,
        )
        output_path = args.outdir / f"day-{day_name.lower()}.pdf"
        pdf.output(str(output_path))
        outputs.append(output_path)

    if outputs:
        print(f"Rendered {len(outputs)} PDFs in {args.outdir}")
    else:
        print("No events found to render.")


if __name__ == "__main__":
    main()
