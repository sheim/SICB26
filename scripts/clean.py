#!/usr/bin/env python3
"""Remove generated files from the workspace."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKIP_DIRS = {".venv", ".git", "node_modules"}
BASE_TARGETS = [
    "schedule.db",
    "events.json",
    "layout.json",
    "output",
    "output-pdf",
    "sicb_itinerary.egg-info",
]


def remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def collect_cache_paths(root: Path) -> list[Path]:
    targets: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}:
            targets.append(path)
        elif path.is_file() and path.suffix == ".pyc":
            targets.append(path)
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove generated files (db, outputs, caches)."
    )
    parser.add_argument(
        "--keep-layout",
        action="store_true",
        help="Keep layout.json (GUI layout overrides).",
    )
    parser.add_argument(
        "--venv",
        action="store_true",
        help="Also remove .venv (Python environment).",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]

    removed = []
    for target in BASE_TARGETS:
        if args.keep_layout and target == "layout.json":
            continue
        path = root / target
        if remove_path(path):
            removed.append(path)

    for path in collect_cache_paths(root):
        if remove_path(path):
            removed.append(path)

    if args.venv:
        venv_path = root / ".venv"
        if remove_path(venv_path):
            removed.append(venv_path)

    if removed:
        print("Removed:")
        for path in sorted(set(removed)):
            print(f"- {path.relative_to(root)}")
    else:
        print("No generated files found.")


if __name__ == "__main__":
    main()
