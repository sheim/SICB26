#!/usr/bin/env python3
"""Remove overlapping events (keep longest) and write a new SQLite database."""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from collections import defaultdict
from pathlib import Path

from schedule_tool import init_db, resolve_room_conflicts

EVENT_COLUMNS = [
    "id",
    "day_name",
    "day_index",
    "date_text",
    "date_iso",
    "start_time",
    "end_time",
    "start_min",
    "end_min",
    "room",
    "title",
    "session",
    "talk_title",
]


def load_events(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, day_name, day_index, date_text, date_iso, start_time, end_time,
               start_min, end_min, room, title, session, talk_title
        FROM events
        ORDER BY day_index, start_min, end_min, id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_meta(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {key: value for key, value in rows}


def dedup_events(events: list[dict]) -> tuple[list[dict], int]:
    grouped: dict[tuple[str | None, str | None], list[dict]] = defaultdict(list)
    passthrough: list[dict] = []

    for event in events:
        if event.get("start_min") is None or event.get("end_min") is None:
            passthrough.append(event)
            continue
        key = (event.get("day_name"), event.get("room"))
        grouped[key].append(event)

    kept = []
    removed_count = 0

    for group_events in grouped.values():
        resolved = resolve_room_conflicts(group_events)
        kept.extend(resolved)
        removed_count += max(0, len(group_events) - len(resolved))

    kept.extend(passthrough)
    kept.sort(key=lambda e: (e.get("day_index", 0), e.get("start_min") or 0, e.get("end_min") or 0, e.get("id", 0)))
    return kept, removed_count


def write_events(conn: sqlite3.Connection, events: list[dict]) -> None:
    rows = []
    for event in events:
        rows.append(tuple(event.get(col) for col in EVENT_COLUMNS))
    conn.executemany(
        """
        INSERT INTO events (
            id, day_name, day_index, date_text, date_iso, start_time, end_time,
            start_min, end_min, room, title, session, talk_title
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def write_meta(conn: sqlite3.Connection, meta: dict[str, str]) -> None:
    rows = [(key, value) for key, value in meta.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        rows,
    )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove overlapping events in the same room/day (keep longest) and "
            "write a new SQLite database."
        )
    )
    parser.add_argument("--db", type=Path, default=Path("schedule.db"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("schedule-dedup.db"),
        help="Output SQLite DB path",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output DB if it already exists",
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"Input DB not found: {args.db}")
    if args.out.exists() and not args.overwrite:
        raise SystemExit(
            f"Output DB already exists: {args.out} (use --overwrite to replace)"
        )

    source_conn = sqlite3.connect(str(args.db))
    events = load_events(source_conn)
    meta = load_meta(source_conn)
    source_conn.close()

    kept, removed = dedup_events(events)

    if args.out.exists():
        args.out.unlink()

    out_conn = init_db(args.out)

    meta["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    meta["deduped_from"] = str(args.db)

    write_events(out_conn, kept)
    write_meta(out_conn, meta)
    out_conn.close()

    print(f"Input events: {len(events)}")
    print(f"Removed overlaps: {removed}")
    print(f"Output events: {len(kept)}")
    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
