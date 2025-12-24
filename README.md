# SICB Itinerary Parser + Timetable Renderer

I was a bit frustrated with the [SICB2026](https://www.xcdsystem.com/sicb/program/ddC9FQp/index.cfm?pgid=2696&RunRemoveSessionFilter=1) "Print My Itinerary" just giving you a list in PDF format, which is not very readable; I would like a timetable. So (with some codex help), here's some Python code that will parse your PDF in a database, which you can then interactively adjust a bit via browser, and finally convert into a table PDF to print for each day.

## Requirements

- Python 3.10+

I recommend setting up with [uv](https://docs.astral.sh/uv/getting-started/installation/); if you're using uv, the lock file is already commited, you can just run `uv sync`.
If you're more familiar with Conda, pip, or something else, you just should just need a `pip install -e .` or equivalent (but not tested).

## Quick start

1. First, create your official itinerary PDF, and save it in this folder (or wherever).

Note, it is generally better to add the entire session rather than individual talks (if you're attending most talks in the session); adding a lot of individual talks tends to make a lot of columns, and there is then very little space for information resulting in short truncated titles that dont' tell you anything. More on that later.

2. Parse the PDF:
    `python3 schedule_tool.py parse itinerary_393889_4913771.pdf --db schedule.db --json events.json`

3. Check and manually modify
    `python3 gui_server.py --db schedule.db --layout layout.json`

4. Create PDF timetable
    `python3 schedule_tool.py render --db schedule.db --outdir output --renderer matrix`

## GUI editor (reorder rooms, hide items)

After running the code, open `http://127.0.0.1:8787` in your browser. Your can:

- drag room headers to reorder columns
- hide items. This is mainly if you already have a PDF with overlapping session and individual talks; you probably want to hide the individual talks in that case.
- toggle session/talk/time/room details and adjust the title truncation length (0 disables truncation).
- click **To misc** on a room header to move that room into shared Misc columns. This is helpful to reduce the total columsn, if there are several rooms where you only have 1-2 talks you're interested in.

####

Options:
- `--page-size` (default `A4`)
- `--orientation` (default `landscape`)
- `--slot-minutes` (default `15`)
- `--font-size` (default `6.5`)
- `--layout` (default `layout.json`)

### Troubleshooting

If PDF rendering fails, install `fpdf2` (`uv pip install -e .[pdf]`).

## Clean generated files

```bash
python3 scripts/clean.py
```
