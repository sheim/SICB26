#!/usr/bin/env python3
"""Local GUI server for reordering rooms and hiding events."""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import layout_config
from schedule_tool import DAY_ORDER, load_events_by_day


class ScheduleHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: Path, db_path: Path, layout_path: Path, **kwargs):
        self.db_path = db_path
        self.layout_path = layout_path
        super().__init__(*args, directory=str(directory), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/days":
            self.handle_days()
            return
        if parsed.path == "/api/events":
            self.handle_events(parsed.query)
            return
        if parsed.path == "/api/layout":
            self.handle_layout()
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/layout":
            self.handle_layout_update()
            return
        self.send_error(404, "Unknown endpoint")

    def handle_days(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        events_by_day = load_events_by_day(conn)
        days = [day for day in DAY_ORDER if day in events_by_day]
        self.send_json(200, {"days": days})

    def handle_events(self, query: str) -> None:
        params = parse_qs(query)
        day = params.get("day", [""])[0]
        conn = sqlite3.connect(str(self.db_path))
        events_by_day = load_events_by_day(conn)
        events = events_by_day.get(day, [])
        events = sorted(events, key=lambda e: (e["start_min"], e["end_min"]))
        self.send_json(200, {"day": day, "events": events})

    def handle_layout(self) -> None:
        layout = layout_config.load_layout(self.layout_path)
        self.send_json(200, layout)

    def handle_layout_update(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return
        layout_config.save_layout(self.layout_path, payload)
        self.send_json(200, {"ok": True})


def run_server(host: str, port: int, db_path: Path, layout_path: Path, ui_dir: Path) -> None:
    handler = lambda *args, **kwargs: ScheduleHandler(
        *args,
        directory=ui_dir,
        db_path=db_path,
        layout_path=layout_path,
        **kwargs,
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"GUI running at http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the timetable GUI server.")
    parser.add_argument("--db", type=Path, default=Path("schedule.db"))
    parser.add_argument("--layout", type=Path, default=Path("layout.json"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--ui-dir", type=Path, default=Path("ui"))
    args = parser.parse_args()

    if not args.ui_dir.exists():
        raise SystemExit(f"UI directory not found: {args.ui_dir}")

    run_server(args.host, args.port, args.db, args.layout, args.ui_dir)


if __name__ == "__main__":
    main()
