#!/usr/bin/env python3
"""Parse the SICB itinerary PDF into SQLite and render day-by-day timetables."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import layout_config
import re
import sqlite3
import subprocess
from pathlib import Path

DAY_ORDER = [
    "Saturday",
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
]
DAY_INDEX = {name: i for i, name in enumerate(DAY_ORDER)}
DAY_ABBR_TO_NAME = {
    "Sat": "Saturday",
    "Sun": "Sunday",
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
}
MONTH_TO_NUM = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
BULLET = "\u2022"
TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", re.IGNORECASE)


def extract_text(pdf_path: Path) -> str:
    try:
        output = subprocess.check_output(
            ["pdftotext", "-layout", str(pdf_path), "-"]
        )
    except FileNotFoundError:
        raise SystemExit("pdftotext is required but was not found on PATH")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pdftotext failed: {exc}")
    return output.decode("utf-8", errors="replace")


def infer_year(text: str) -> int | None:
    for line in text.splitlines()[:50]:
        if "SICB" in line:
            match = re.search(r"\b(\d{4})\b", line)
            if match:
                return int(match.group(1))
    return None


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_time_to_minutes(value: str) -> int | None:
    match = TIME_RE.match(value.strip().upper())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = match.group(3).upper()
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour * 60 + minute


def minutes_to_label(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    ampm = "AM" if hour < 12 else "PM"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour}:{minute:02d} {ampm}"


def truncate_text(text: str, max_length: int | None) -> str:
    if not text:
        return ""
    if not max_length or max_length <= 0:
        return text
    if len(text) <= max_length:
        return text
    suffix = "..."
    if max_length <= len(suffix):
        return text[:max_length]
    trimmed = text[: max_length - len(suffix)].rstrip()
    if not trimmed:
        return text[:max_length]
    return trimmed + suffix


def normalize_display_settings(
    display_options: dict | None, title_max_length: int | None
) -> tuple[dict, int]:
    display = dict(layout_config.DEFAULT_DISPLAY_OPTIONS)
    if display_options:
        display.update(display_options)
    if title_max_length is None:
        title_max_length = layout_config.DEFAULT_TITLE_MAX_LENGTH
    return display, title_max_length


def parse_date_line(line: str, inferred_year: int | None) -> dict | None:
    parts = [normalize_space(part) for part in line.split(BULLET)]
    if len(parts) < 3:
        return None
    date_part = parts[0]
    time_part = parts[1]
    room_part = parts[2]

    if date_part.startswith("Date:"):
        date_part = date_part[len("Date:") :].strip()
    if time_part.startswith("Time:"):
        time_part = time_part[len("Time:") :].strip()
    if room_part.startswith("Room:"):
        room_part = room_part[len("Room:") :].strip()

    dow_abbr = None
    month_name = None
    day_number = None
    if "," in date_part:
        dow_abbr, rest = [part.strip() for part in date_part.split(",", 1)]
        rest_parts = rest.split()
        if len(rest_parts) >= 2:
            month_name = rest_parts[0]
            day_number = int(rest_parts[1])
    if not dow_abbr or not month_name or day_number is None:
        return None

    day_name = DAY_ABBR_TO_NAME.get(dow_abbr, dow_abbr)
    start_time = None
    end_time = None
    if "-" in time_part:
        start_raw, end_raw = [normalize_space(part) for part in re.split(r"\s*-\s*", time_part, maxsplit=1)]
        start_time = start_raw
        end_time = end_raw
    else:
        start_time = time_part
        end_time = time_part

    start_min = parse_time_to_minutes(start_time) if start_time else None
    end_min = parse_time_to_minutes(end_time) if end_time else None

    date_text = f"{dow_abbr}, {month_name} {day_number:02d}"
    date_iso = None
    if inferred_year and month_name in MONTH_TO_NUM:
        date_iso = f"{inferred_year:04d}-{MONTH_TO_NUM[month_name]:02d}-{day_number:02d}"

    return {
        "day_name": day_name,
        "date_text": date_text,
        "date_iso": date_iso,
        "start_time": start_time,
        "end_time": end_time,
        "start_min": start_min,
        "end_min": end_min,
        "room": room_part,
    }


def parse_block_lines(lines: list[str]) -> dict:
    session_lines: list[str] = []
    talk_lines: list[str] = []
    title_lines: list[str] = []
    mode: str | None = None

    for raw_line in lines:
        line = normalize_space(raw_line)
        if not line:
            continue
        if line.startswith("Session:"):
            mode = "session"
            session_lines.append(line[len("Session:") :].strip())
            continue
        if line.startswith("Talk Title:"):
            mode = "talk"
            talk_lines.append(line[len("Talk Title:") :].strip())
            continue
        if line.startswith("Session "):
            mode = "session"
            session_lines.append(line)
            continue

        if mode == "session":
            session_lines.append(line)
        elif mode == "talk":
            talk_lines.append(line)
        else:
            title_lines.append(line)

    session = normalize_space(" ".join(session_lines)) if session_lines else None
    talk_title = normalize_space(" ".join(talk_lines)) if talk_lines else None
    title = normalize_space(" ".join(title_lines)) if title_lines else None

    if not title:
        if talk_title:
            title = talk_title
        elif session:
            title = session

    return {
        "session": session,
        "talk_title": talk_title,
        "title": title,
    }


def parse_events(text: str) -> list[dict]:
    inferred_year = infer_year(text)
    lines = [line.strip() for line in text.splitlines()]
    events: list[dict] = []
    current_day: str | None = None
    buffer: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if current_day is None and line not in DAY_ORDER:
            i += 1
            continue
        if line in DAY_ORDER:
            current_day = line
            i += 1
            continue
        if line.startswith("Date:"):
            date_line = line
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break
                if next_line in DAY_ORDER:
                    break
                if next_line.startswith(("Session:", "Talk Title:", "Date:")):
                    break
                date_line = normalize_space(f"{date_line} {next_line}")
                j += 1
            date_info = parse_date_line(date_line, inferred_year)
            block_info = parse_block_lines(buffer)
            if date_info:
                day_name = date_info["day_name"]
                if current_day and current_day != day_name:
                    day_name = current_day
                event = {
                    **date_info,
                    "day_name": day_name,
                    "day_index": DAY_INDEX.get(day_name, 99),
                    **block_info,
                }
                events.append(event)
            buffer = []
            i = j
            continue
        buffer.append(line)
        i += 1
    return events


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            day_name TEXT NOT NULL,
            day_index INTEGER NOT NULL,
            date_text TEXT,
            date_iso TEXT,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            start_min INTEGER,
            end_min INTEGER,
            room TEXT,
            title TEXT,
            session TEXT,
            talk_title TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    return conn


def load_events(conn: sqlite3.Connection, events: list[dict], source_pdf: str) -> None:
    conn.execute("DELETE FROM events")
    conn.execute("DELETE FROM meta")
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("source_pdf", source_pdf),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ("generated_at", dt.datetime.now(dt.timezone.utc).isoformat()),
    )

    rows = [
        (
            event.get("day_name"),
            event.get("day_index"),
            event.get("date_text"),
            event.get("date_iso"),
            event.get("start_time"),
            event.get("end_time"),
            event.get("start_min"),
            event.get("end_min"),
            event.get("room"),
            event.get("title"),
            event.get("session"),
            event.get("talk_title"),
        )
        for event in events
    ]
    conn.executemany(
        """
        INSERT INTO events (
            day_name,
            day_index,
            date_text,
            date_iso,
            start_time,
            end_time,
            start_min,
            end_min,
            room,
            title,
            session,
            talk_title
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def group_overlaps(events: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_end = -1
    for event in sorted(events, key=lambda e: (e["start_min"], e["end_min"])):
        if not current or event["start_min"] < current_end:
            current.append(event)
            current_end = max(current_end, event["end_min"])
        else:
            groups.append(current)
            current = [event]
            current_end = event["end_min"]
    if current:
        groups.append(current)
    return groups


def assign_lanes(events: list[dict]) -> None:
    for group in group_overlaps(events):
        lanes_end: list[int] = []
        for event in sorted(group, key=lambda e: (e["start_min"], e["end_min"])):
            placed = False
            for idx, lane_end in enumerate(lanes_end):
                if event["start_min"] >= lane_end:
                    event["lane"] = idx
                    lanes_end[idx] = event["end_min"]
                    placed = True
                    break
            if not placed:
                event["lane"] = len(lanes_end)
                lanes_end.append(event["end_min"])
        lane_count = max(1, len(lanes_end))
        for event in group:
            event["lane_count"] = lane_count


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


def select_day_label(events: list[dict]) -> str:
    if not events:
        return ""
    counts = collections.Counter(event.get("date_text") for event in events if event.get("date_text"))
    if counts:
        return counts.most_common(1)[0][0]
    return events[0]["day_name"]


def load_events_by_day(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    rows = conn.execute(
        """
        SELECT id, day_name, day_index, date_text, date_iso, start_time, end_time,
               start_min, end_min, room, title, session, talk_title
        FROM events
        ORDER BY day_index, start_min, end_min
        """
    ).fetchall()
    events_by_day: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        event = {
            "id": row[0],
            "day_name": row[1],
            "day_index": row[2],
            "date_text": row[3],
            "date_iso": row[4],
            "start_time": row[5],
            "end_time": row[6],
            "start_min": row[7],
            "end_min": row[8],
            "room": row[9],
            "title": row[10],
            "session": row[11],
            "talk_title": row[12],
        }
        events_by_day[event["day_name"]].append(event)
    return events_by_day


def intervals_overlap(left: dict, right: dict) -> bool:
    return left["start_min"] < right["end_min"] and right["start_min"] < left["end_min"]


def resolve_room_conflicts(events: list[dict]) -> list[dict]:
    resolved: list[dict] = []
    for event in sorted(events, key=lambda e: (e["start_min"], e["end_min"])):
        conflicts = [existing for existing in resolved if intervals_overlap(event, existing)]
        if not conflicts:
            resolved.append(event)
            continue
        duration = event["end_min"] - event["start_min"]
        longer_than_all = True
        for existing in conflicts:
            existing_duration = existing["end_min"] - existing["start_min"]
            if duration <= existing_duration:
                longer_than_all = False
                break
        if longer_than_all:
            for conflict in conflicts:
                resolved.remove(conflict)
            resolved.append(event)
    return resolved


def render_day_timeline_html(
    day_name: str,
    day_label: str,
    events: list[dict],
    display_options: dict | None = None,
    title_max_length: int | None = None,
) -> str:
    events = [event for event in events if event.get("start_min") is not None and event.get("end_min") is not None]
    if not events:
        return ""
    display, title_max_length = normalize_display_settings(
        display_options, title_max_length
    )
    assign_lanes(events)
    day_start = min(event["start_min"] for event in events)
    day_end = max(event["end_min"] for event in events)
    day_start = (day_start // 30) * 30
    day_end = ((day_end + 29) // 30) * 30

    pixels_per_min = 1.3
    timeline_height = int((day_end - day_start) * pixels_per_min) + 1
    gutter_width = 96
    lane_gap = 8

    time_labels = []
    for minute in range(day_start, day_end + 1, 30):
        top = int((minute - day_start) * pixels_per_min)
        time_labels.append((minute, top))

    event_cards = []
    for event in events:
        top = int((event["start_min"] - day_start) * pixels_per_min)
        height = max(16, int((event["end_min"] - event["start_min"]) * pixels_per_min))
        lane_count = event.get("lane_count", 1)
        lane_index = event.get("lane", 0)
        width = f"calc((100% - {gutter_width}px - {(lane_count - 1) * lane_gap}px) / {lane_count})"
        left = f"calc({gutter_width}px + {lane_index} * ({width} + {lane_gap}px))"
        raw_title = event.get("title") or "(Untitled)"
        title = html.escape(truncate_text(raw_title, title_max_length))
        session = event.get("session") or ""
        talk_title = event.get("talk_title") or ""
        session_lines: list[str] = []
        if display.get("show_session") and session and session != raw_title:
            session_lines.append(truncate_text(session, title_max_length))
        if (
            display.get("show_talk_title")
            and talk_title
            and talk_title != raw_title
            and talk_title not in session_lines
        ):
            session_lines.append(truncate_text(talk_title, title_max_length))
        session_text = html.escape(" / ".join(session_lines))
        room = event.get("room") or ""
        time_range = f"{event.get('start_time', '')} - {event.get('end_time', '')}".strip(" -")
        if not display.get("show_time"):
            time_range = ""
        if not display.get("show_room"):
            room = ""
        event_cards.append(
            {
                "top": top,
                "height": height,
                "left": left,
                "width": width,
                "title": title,
                "session": session_text,
                "room": html.escape(room),
                "time_range": html.escape(time_range),
            }
        )

    css = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600&family=Space+Grotesk:wght@400;600&display=swap');
:root {
  --paper: #f5f0e6;
  --ink: #1c1b1a;
  --accent: #c86b2d;
  --muted: #6b665f;
  --grid: rgba(46, 42, 37, 0.12);
  --event-bg: #fffdf7;
  --event-border: rgba(46, 42, 37, 0.2);
  --shadow: rgba(28, 27, 26, 0.15);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(circle at 12% 8%, #f9f4ea 0%, #f0e8da 45%, #e9e1d1 100%);
  color: var(--ink);
  font-family: 'Space Grotesk', 'Avenir Next', 'Segoe UI', sans-serif;
}
.page {
  max-width: 980px;
  margin: 28px auto;
  background: var(--paper);
  border-radius: 18px;
  box-shadow: 0 18px 45px var(--shadow);
  padding: 32px 36px 40px;
  position: relative;
  overflow: hidden;
}
.page::before {
  content: "";
  position: absolute;
  inset: -40% 55% 40% -20%;
  background: linear-gradient(130deg, rgba(200, 107, 45, 0.12), transparent 55%);
  transform: rotate(-8deg);
  pointer-events: none;
}
header {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}
header h1 {
  font-family: 'Fraunces', 'Georgia', serif;
  font-size: 32px;
  margin: 0 0 4px;
  letter-spacing: 0.4px;
}
header .subtitle {
  font-size: 14px;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: var(--muted);
}
.timeline {
  position: relative;
  margin-top: 24px;
}
.timeline-grid {
  position: absolute;
  left: var(--gutter);
  right: 0;
  top: 0;
  height: 100%;
  background-image: linear-gradient(to bottom, var(--grid) 1px, transparent 1px);
  background-size: 100% 30px;
  border-radius: 14px;
}
.time-label {
  position: absolute;
  left: 0;
  width: calc(var(--gutter) - 12px);
  text-align: right;
  padding-right: 12px;
  font-size: 12px;
  color: var(--muted);
}
.event {
  position: absolute;
  background: var(--event-bg);
  border: 1px solid var(--event-border);
  border-left: 4px solid var(--accent);
  border-radius: 10px;
  padding: 8px 10px 9px;
  box-shadow: 0 6px 18px rgba(25, 22, 19, 0.08);
  overflow: hidden;
}
.event .title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}
.event .meta {
  font-size: 11px;
  color: var(--muted);
  line-height: 1.35;
}
.event .meta:empty {
  display: none;
}
.event .session {
  font-size: 11px;
  color: var(--ink);
  opacity: 0.75;
}
.event .session:empty {
  display: none;
}
@media print {
  body {
    background: #ffffff;
  }
  .page {
    margin: 0;
    border-radius: 0;
    box-shadow: none;
    padding: 24px 28px 32px;
  }
  .page::before {
    display: none;
  }
}
"""

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(day_name)} timetable</title>",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        "<div class=\"page\">",
        "<header>",
        f"<div class=\"subtitle\">SICB itinerary</div>",
        f"<h1>{html.escape(day_name)}</h1>",
        f"<div class=\"subtitle\">{html.escape(day_label)}</div>",
        "</header>",
        f"<div class=\"timeline\" style=\"height: {timeline_height}px; --gutter: {gutter_width}px;\">",
        f"<div class=\"timeline-grid\"></div>",
    ]

    for minute, top in time_labels:
        label = minutes_to_label(minute)
        html_parts.append(
            f"<div class=\"time-label\" style=\"top:{top - 6}px;\">{html.escape(label)}</div>"
        )

    for card in event_cards:
        html_parts.append(
            """
<div class="event" style="top:{top}px; height:{height}px; left:{left}; width:{width};">
  <div class="title">{title}</div>
  <div class="session">{session}</div>
  <div class="meta">{time_range}</div>
  <div class="meta">{room}</div>
</div>
""".format(**card)
        )

    html_parts.extend([
        "</div>",
        "</div>",
        "</body>",
        "</html>",
    ])
    return "\n".join(html_parts)


def render_day_table_html(
    day_name: str,
    day_label: str,
    events: list[dict],
    display_options: dict | None = None,
    title_max_length: int | None = None,
) -> str:
    events = [
        event
        for event in events
        if event.get("start_min") is not None and event.get("end_min") is not None
    ]
    if not events:
        return ""

    display, title_max_length = normalize_display_settings(
        display_options, title_max_length
    )

    events = sorted(
        events,
        key=lambda e: (
            e["start_min"],
            e["end_min"],
            (e.get("room") or ""),
            (e.get("title") or ""),
        ),
    )

    css = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600&family=Space+Grotesk:wght@400;600&display=swap');
:root {
  --paper: #f5f0e6;
  --ink: #1c1b1a;
  --accent: #c86b2d;
  --muted: #6b665f;
  --grid: rgba(46, 42, 37, 0.12);
  --event-bg: #fffdf7;
  --row-alt: #f0e7d6;
  --shadow: rgba(28, 27, 26, 0.15);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(circle at 12% 8%, #f9f4ea 0%, #f0e8da 45%, #e9e1d1 100%);
  color: var(--ink);
  font-family: 'Space Grotesk', 'Avenir Next', 'Segoe UI', sans-serif;
}
.page {
  max-width: 1080px;
  margin: 28px auto;
  background: var(--paper);
  border-radius: 18px;
  box-shadow: 0 18px 45px var(--shadow);
  padding: 32px 36px 40px;
  position: relative;
  overflow: hidden;
}
.page::before {
  content: "";
  position: absolute;
  inset: -40% 55% 40% -20%;
  background: linear-gradient(130deg, rgba(200, 107, 45, 0.12), transparent 55%);
  transform: rotate(-8deg);
  pointer-events: none;
}
header {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}
header h1 {
  font-family: 'Fraunces', 'Georgia', serif;
  font-size: 32px;
  margin: 0 0 4px;
  letter-spacing: 0.4px;
}
header .subtitle {
  font-size: 14px;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: var(--muted);
}
.table-wrap {
  margin-top: 24px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(46, 42, 37, 0.18);
  background: var(--event-bg);
}
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
thead th {
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  color: var(--muted);
  padding: 12px 14px;
  background: rgba(46, 42, 37, 0.06);
  border-bottom: 1px solid rgba(46, 42, 37, 0.18);
}
tbody td {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(46, 42, 37, 0.12);
  vertical-align: top;
  font-size: 13px;
  line-height: 1.45;
}
tbody tr:nth-child(even) td {
  background: var(--row-alt);
}
.col-time {
  width: 160px;
  white-space: nowrap;
  font-weight: 600;
}
.col-room {
  width: 230px;
}
.title {
  font-weight: 600;
}
.detail {
  margin-top: 4px;
  font-size: 12px;
  color: var(--muted);
}
.room {
  font-weight: 600;
}
.wrap {
  overflow-wrap: anywhere;
}
@media print {
  body {
    background: #ffffff;
  }
  .page {
    margin: 0;
    border-radius: 0;
    box-shadow: none;
    padding: 24px 28px 32px;
  }
  .page::before {
    display: none;
  }
  tbody tr:nth-child(even) td {
    background: transparent;
  }
}
"""

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(day_name)} timetable</title>",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        "<div class=\"page\">",
        "<header>",
        f"<div class=\"subtitle\">SICB itinerary</div>",
        f"<h1>{html.escape(day_name)}</h1>",
        f"<div class=\"subtitle\">{html.escape(day_label)}</div>",
        "</header>",
        "<div class=\"table-wrap\">",
        "<table>",
        "<thead>",
        "<tr>",
    ]

    if display.get("show_time"):
        html_parts.append("<th class=\"col-time\">Time</th>")
    html_parts.append("<th>Event</th>")
    if display.get("show_room"):
        html_parts.append("<th class=\"col-room\">Room</th>")
    html_parts.extend([
        "</tr>",
        "</thead>",
        "<tbody>",
    ])

    for event in events:
        time_range = (
            f"{event.get('start_time', '')} - {event.get('end_time', '')}"
        ).strip(" -")
        raw_title = event.get("title") or "(Untitled)"
        title = html.escape(truncate_text(raw_title, title_max_length))
        details = []
        session = event.get("session")
        if display.get("show_session") and session and session != raw_title:
            details.append(truncate_text(session, title_max_length))
        talk_title = event.get("talk_title")
        if (
            display.get("show_talk_title")
            and talk_title
            and talk_title != raw_title
            and talk_title not in details
        ):
            details.append(truncate_text(talk_title, title_max_length))
        detail_html = "".join(
            f"<div class=\"detail\">{html.escape(detail)}</div>" for detail in details
        )
        row_cells = []
        if display.get("show_time"):
            row_cells.append(
                f"<td class=\"col-time\">{html.escape(time_range)}</td>"
            )
        row_cells.append(
            """
  <td class="wrap">
    <div class="title">{title}</div>
    {detail_html}
  </td>
""".format(
                title=title,
                detail_html=detail_html,
            ).strip()
        )
        if display.get("show_room"):
            room = html.escape(event.get("room") or "")
            row_cells.append(
                """
  <td class="col-room wrap">
    <div class="room">{room}</div>
  </td>
""".format(
                    room=room
                ).strip()
            )
        html_parts.append("<tr>\n" + "\n".join(row_cells) + "\n</tr>")

    html_parts.extend([
        "</tbody>",
        "</table>",
        "</div>",
        "</div>",
        "</body>",
        "</html>",
    ])
    return "\n".join(html_parts)


def render_day_matrix_html(
    day_name: str,
    day_label: str,
    events: list[dict],
    pdf_mode: bool = False,
    page_size: str = "A4",
    orientation: str = "landscape",
    room_order_override: list[str] | None = None,
    misc_rooms_override: list[str] | None = None,
    display_options: dict | None = None,
    title_max_length: int | None = None,
) -> str:
    events = [
        event
        for event in events
        if event.get("start_min") is not None and event.get("end_min") is not None
    ]
    if not events:
        return ""

    display, title_max_length = normalize_display_settings(
        display_options, title_max_length
    )

    slot_minutes = 15
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
    misc_rooms: list[str] = []
    for idx, lane in enumerate(misc_lanes):
        label = "Misc" if idx == 0 else f"Misc {idx + 1}"
        misc_rooms.append(label)
        events_by_room[label] = lane

    rooms.extend(misc_rooms)

    all_events = [event for room in rooms for event in events_by_room.get(room, [])]
    if not all_events:
        return ""

    day_start = min(event["start_min"] for event in all_events)
    day_end = max(event["end_min"] for event in all_events)
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

    page_rule = ""
    matrix_overflow = "auto"
    table_width = "max-content"
    table_layout = "auto"
    if pdf_mode:
        page_rule = f"@page {{ size: {page_size} {orientation}; margin: 10mm; }}\\n"
        matrix_overflow = "visible"
        table_width = "100%"
        table_layout = "fixed"

    css_template = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600&family=Space+Grotesk:wght@400;600&display=swap');
:root {
  --paper: #f5f0e6;
  --ink: #1c1b1a;
  --accent: #c86b2d;
  --muted: #6b665f;
  --grid: rgba(46, 42, 37, 0.12);
  --event-bg: #fffdf7;
  --row-alt: #f0e7d6;
  --shadow: rgba(28, 27, 26, 0.15);
  --slot-height: 28px;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: radial-gradient(circle at 12% 8%, #f9f4ea 0%, #f0e8da 45%, #e9e1d1 100%);
  color: var(--ink);
  font-family: 'Space Grotesk', 'Avenir Next', 'Segoe UI', sans-serif;
}
.page {
  max-width: 1200px;
  margin: 28px auto;
  background: var(--paper);
  border-radius: 18px;
  box-shadow: 0 18px 45px var(--shadow);
  padding: 32px 36px 40px;
  position: relative;
  overflow: hidden;
}
.page::before {
  content: "";
  position: absolute;
  inset: -40% 55% 40% -20%;
  background: linear-gradient(130deg, rgba(200, 107, 45, 0.12), transparent 55%);
  transform: rotate(-8deg);
  pointer-events: none;
}
header {
  position: relative;
  z-index: 1;
  margin-bottom: 18px;
}
header h1 {
  font-family: 'Fraunces', 'Georgia', serif;
  font-size: 32px;
  margin: 0 0 4px;
  letter-spacing: 0.4px;
}
header .subtitle {
  font-size: 14px;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: var(--muted);
}
.matrix-wrap {
  margin-top: 24px;
  border-radius: 14px;
  overflow: __MATRIX_OVERFLOW__;
  border: 1px solid rgba(46, 42, 37, 0.18);
  background: var(--event-bg);
}
table {
  width: __TABLE_WIDTH__;
  min-width: 100%;
  border-collapse: collapse;
  table-layout: __TABLE_LAYOUT__;
}
thead th {
  position: sticky;
  top: 0;
  background: rgba(46, 42, 37, 0.06);
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  color: var(--muted);
  padding: 10px 12px;
  border-bottom: 1px solid rgba(46, 42, 37, 0.18);
  z-index: 2;
}
.time-col {
  width: 96px;
  min-width: 96px;
  white-space: nowrap;
  font-weight: 600;
  background: rgba(46, 42, 37, 0.04);
}
tbody tr {
  height: var(--slot-height);
}
tbody tr.hour-row td.time-col {
  color: var(--ink);
}
tbody tr.half-row td.time-col {
  color: var(--muted);
}
tbody td {
  border-bottom: 1px solid rgba(46, 42, 37, 0.1);
  border-right: 1px solid rgba(46, 42, 37, 0.08);
  vertical-align: top;
  padding: 6px 8px;
  font-size: 12px;
  line-height: 1.35;
}
tbody td.empty {
  background: linear-gradient(90deg, rgba(255, 253, 247, 0.8), rgba(255, 253, 247, 0.6));
}
.event-cell {
  background: #fffdf7;
  border-left: 3px solid var(--accent);
  overflow-wrap: anywhere;
}
.event-title {
  font-weight: 600;
  font-size: 12px;
}
.event-detail {
  margin-top: 4px;
  font-size: 11px;
  color: var(--muted);
}
.event-room {
  margin-top: 4px;
  font-size: 11px;
  color: var(--muted);
  font-weight: 600;
}
@media print {
  body {
    background: #ffffff;
  }
  .page {
    margin: 0;
    border-radius: 0;
    box-shadow: none;
    padding: 24px 28px 32px;
  }
  .page::before {
    display: none;
  }
  thead th {
    position: static;
  }
}
"""
    css = (
        page_rule
        + css_template.replace("__MATRIX_OVERFLOW__", matrix_overflow)
        .replace("__TABLE_WIDTH__", table_width)
        .replace("__TABLE_LAYOUT__", table_layout)
    )

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(day_name)} schedule</title>",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        "<div class=\"page\">",
        "<header>",
        f"<div class=\"subtitle\">SICB itinerary</div>",
        f"<h1>{html.escape(day_name)}</h1>",
        f"<div class=\"subtitle\">{html.escape(day_label)}</div>",
        "</header>",
        "<div class=\"matrix-wrap\">",
        "<table>",
        "<thead>",
        "<tr>",
        "<th class=\"time-col\">Time</th>",
    ]

    for room in rooms:
        html_parts.append(f"<th>{html.escape(room)}</th>")

    html_parts.extend([
        "</tr>",
        "</thead>",
        "<tbody>",
    ])

    for slot in time_slots:
        minutes = slot % 60
        row_class = "hour-row" if minutes == 0 else "half-row" if minutes == 30 else "minor-row"
        html_parts.append(f"<tr class=\"{row_class}\">")
        html_parts.append(f"<td class=\"time-col\">{html.escape(minutes_to_label(slot))}</td>")
        for room in rooms:
            if slot in room_skips.get(room, set()):
                continue
            if slot in room_starts.get(room, {}):
                event = room_starts[room][slot]
                rowspan = event.get("_rowspan", 1)
                title_value = event.get("title") or "(Untitled)"
                title = html.escape(truncate_text(title_value, title_max_length))
                details = []
                session = event.get("session")
                if display.get("show_session") and session and session != title_value:
                    details.append(truncate_text(session, title_max_length))
                talk_title = event.get("talk_title")
                if (
                    display.get("show_talk_title")
                    and talk_title
                    and talk_title != title_value
                    and talk_title not in details
                ):
                    details.append(truncate_text(talk_title, title_max_length))
                time_range = (
                    f"{event.get('start_time', '')} - {event.get('end_time', '')}"
                ).strip(" -")
                if time_range and display.get("show_time"):
                    details.append(time_range)
                misc_room = event.get("_misc_source_room")
                detail_html = ""
                if misc_room and display.get("show_room"):
                    detail_html += (
                        f"<div class=\"event-room\">Room: {html.escape(misc_room)}</div>"
                    )
                if details:
                    detail_html += "".join(
                        f"<div class=\"event-detail\">{html.escape(detail)}</div>"
                        for detail in details
                    )
                html_parts.append(
                    """
<td class="event-cell" rowspan="{rowspan}">
  <div class="event-title">{title}</div>
  {detail_html}
</td>
""".format(
                        rowspan=rowspan,
                        title=title,
                        detail_html=detail_html,
                    )
                )
            else:
                html_parts.append("<td class=\"empty\"></td>")
        html_parts.append("</tr>")

    html_parts.extend([
        "</tbody>",
        "</table>",
        "</div>",
        "</div>",
        "</body>",
        "</html>",
    ])
    return "\n".join(html_parts)


def render_html(
    conn: sqlite3.Connection,
    outdir: Path,
    renderer: str,
    layout_path: Path | None = None,
) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    events_by_day = load_events_by_day(conn)
    layout = layout_config.load_layout(layout_path) if layout_path else None
    display_options, title_max_length = layout_config.get_display_settings(layout)

    output_files: list[Path] = []
    index_links = []
    renderers = {
        "timeline": render_day_timeline_html,
        "table": render_day_table_html,
        "matrix": render_day_matrix_html,
    }
    render_day = renderers[renderer]
    for day_name in DAY_ORDER:
        events = events_by_day.get(day_name, [])
        if not events:
            continue
        room_order: list[str] = []
        misc_rooms: list[str] = []
        if layout:
            events, room_order, misc_rooms = layout_config.apply_layout(
                events, day_name, layout
            )
            if not events:
                continue
        label = select_day_label(events)
        if renderer == "matrix":
            html_content = render_day(
                day_name,
                label,
                events,
                room_order_override=room_order,
                misc_rooms_override=misc_rooms,
                display_options=display_options,
                title_max_length=title_max_length,
            )
        else:
            html_content = render_day(
                day_name,
                label,
                events,
                display_options=display_options,
                title_max_length=title_max_length,
            )
        filename = f"day-{day_name.lower()}.html"
        filepath = outdir / filename
        filepath.write_text(html_content, encoding="utf-8")
        output_files.append(filepath)
        index_links.append((day_name, filename))

    index_html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SICB timetable index</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: 'Space Grotesk', 'Avenir Next', 'Segoe UI', sans-serif; margin: 40px; color: #1c1b1a; }
    h1 { font-family: 'Fraunces', 'Georgia', serif; }
    a { color: #c86b2d; text-decoration: none; }
    li { margin: 8px 0; }
  </style>
</head>
<body>
  <h1>SICB timetable</h1>
  <ul>
"""
    for day_name, filename in index_links:
        index_html += f"    <li><a href=\"{filename}\">{day_name}</a></li>\n"
    index_html += """  </ul>
</body>
</html>
"""
    (outdir / "index.html").write_text(index_html, encoding="utf-8")
    output_files.append(outdir / "index.html")
    return output_files


def parse_pdf_to_db(pdf_path: Path, db_path: Path, json_path: Path | None) -> int:
    text = extract_text(pdf_path)
    events = parse_events(text)
    if not events:
        raise SystemExit("No events parsed from PDF")
    conn = init_db(db_path)
    load_events(conn, events, pdf_path.name)
    if json_path:
        json_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    return len(events)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse a SICB itinerary PDF into SQLite and render HTML timetables."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_parser = subparsers.add_parser("parse", help="Parse PDF and load SQLite")
    parse_parser.add_argument("pdf", type=Path, help="Path to itinerary PDF")
    parse_parser.add_argument("--db", type=Path, default=Path("schedule.db"))
    parse_parser.add_argument("--json", type=Path, help="Optional JSON output path")

    render_parser = subparsers.add_parser("render", help="Render timetable output")
    render_parser.add_argument("--db", type=Path, default=Path("schedule.db"))
    render_parser.add_argument("--outdir", type=Path, default=Path("output"))
    render_parser.add_argument(
        "--renderer",
        choices=["table", "timeline", "matrix"],
        default="table",
        help="Output renderer",
    )
    render_parser.add_argument(
        "--layout",
        type=Path,
        default=Path("layout.json"),
        help="Layout overrides JSON",
    )

    args = parser.parse_args()

    if args.command == "parse":
        count = parse_pdf_to_db(args.pdf, args.db, args.json)
        print(f"Parsed {count} events into {args.db}")
        return

    if args.command == "render":
        conn = init_db(args.db)
        outputs = render_html(
            conn,
            args.outdir,
            args.renderer,
            layout_path=args.layout,
        )
        print(f"Rendered {len(outputs)} files in {args.outdir}")


if __name__ == "__main__":
    main()
