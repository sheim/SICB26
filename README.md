# SICB Itinerary Parser + Timetable Renderer

Parse a SICB itinerary PDF into SQLite and render printable HTML schedules or PDFs.

## Requirements

- Python 3.10+
- `pdftotext` on PATH (from Poppler)
- For direct PDF output: `fpdf2` (Python, no system deps)
- For HTML-to-PDF output: `weasyprint` (Python) or `wkhtmltopdf` (system tool)

## Quick start

```bash
python3 schedule_tool.py parse itinerary_393889_0231776.pdf --db schedule.db --json events.json
python3 schedule_tool.py render --db schedule.db --outdir output --renderer matrix
```

Open `output/index.html` to navigate to each day.

## GUI editor (reorder rooms, hide items)

```bash
python3 gui_server.py --db schedule.db --layout layout.json
```

Then open `http://127.0.0.1:8787` in your browser. Drag room headers to reorder columns, hide items, and click **Save layout**. The saved layout is stored in `layout.json` and used by matrix renderers.

## Using uv (optional)

```bash
uv venv
uv pip install -e .
# For direct PDF output:
uv pip install -e .[pdf]
# For HTML-to-PDF output (matrix-pdf renderer):
uv pip install -e .[pdf-html]
uv run schedule-tool parse itinerary_393889_0231776.pdf --db schedule.db --json events.json
uv run schedule-tool render --db schedule.db --outdir output --renderer matrix
```

You can also run without installing:

```bash
uv run python schedule_tool.py render --db schedule.db --outdir output --renderer matrix
```

## Commands

### Parse

```bash
python3 schedule_tool.py parse <pdf> --db schedule.db [--json events.json]
```

- `--db`: SQLite output path (default `schedule.db`).
- `--json`: optional JSON export of parsed events.

### Render

```bash
python3 schedule_tool.py render --db schedule.db --outdir output --renderer <renderer>
```

Renderers:
- `table` (default): list table by time with event + room columns.
- `timeline`: overlap-aware vertical timeline with lanes.
- `matrix`: time on rows, rooms as columns (uses rowspans).
- `matrix-pdf`: same matrix view rendered to PDF (A4 landscape by default).

PDF options (matrix-pdf only):
- `--page-size` (default `A4`)
- `--orientation` (default `landscape`)

Layout options:
- `--layout` (default `layout.json`)

## Direct matrix PDF (no HTML)

```bash
python3 render_matrix_pdf.py --db schedule.db --outdir output-pdf
```

Options:
- `--page-size` (default `A4`)
- `--orientation` (default `landscape`)
- `--slot-minutes` (default `15`)
- `--font-size` (default `6.5`)
- `--layout` (default `layout.json`)

## Matrix overlap behavior

When two events overlap in the same room/time (e.g., a session block and an individual talk), the renderer keeps the more specific talk and ignores the broader session. The kept cell includes `Overlap ignored (N)` as a placeholder for a smarter conflict UI later.

## Output files

- `schedule.db`: SQLite database of events
- `events.json`: optional JSON export
- `output/index.html`: index page for rendered days
- `output/day-<day>.html`: one file per day
- `output/day-<day>.pdf`: one PDF per day when using `matrix-pdf`
- `output-pdf/day-<day>.pdf`: one PDF per day when using `render_matrix_pdf.py`
- `layout.json`: GUI layout overrides (room order + hidden items)

## Notes and customization

- The matrix renderer uses 15-minute time slots; see `slot_minutes` in `schedule_tool.py` if you want a different granularity.
- The parser expects the PDF to have day headers and lines with `Date: ... • Time: ... • Room: ...` formatting.

## Troubleshooting

If parsing fails with a `pdftotext` error, install Poppler and ensure `pdftotext` is available on your PATH.

If HTML-to-PDF rendering fails, install `weasyprint` (`uv pip install -e .[pdf-html]`) or `wkhtmltopdf`.
