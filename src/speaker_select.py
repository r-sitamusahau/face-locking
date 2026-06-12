"""
Interactive speaker selection from enrolled face database.
Used at startup by vision_node and face_locking for assessor demos.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

try:
    from .recognize import load_db_npz
except ImportError:
    sys.path.append(str(Path(__file__).parent.parent))
    from src.recognize import load_db_npz


def default_db_path() -> Path:
    return Path(__file__).parent.parent / "data" / "db" / "face_db.npz"


def list_enrolled_speakers(db_path: Optional[Path] = None) -> List[str]:
    path = db_path or default_db_path()
    db = load_db_npz(path)
    return sorted(db.keys())


def prompt_select_speaker(
    db_path: Optional[Path] = None,
    *,
    default: Optional[str] = None,
    allow_default: bool = True,
) -> str:
    """
    Show a numbered menu of enrolled speakers and return the chosen name.
    If only one speaker exists, select it automatically.
    """
    path = db_path or default_db_path()
    names = list_enrolled_speakers(path)

    if not path.exists() or not names:
        print(f"\nERROR: No enrolled speakers in {path}")
        print("Enroll someone first, e.g.:")
        print("  python -m src.enroll --name ruth --auto")
        sys.exit(1)

    if len(names) == 1:
        chosen = names[0]
        print(f"\n[Speaker Lock] Only one enrolled speaker: {chosen}")
        return chosen

    print("\n" + "=" * 44)
    print("  SELECT SPEAKER TO LOCK")
    print("=" * 44)
    print(f"  Database: {path.name}")
    print()
    for i, name in enumerate(names, start=1):
        marker = " (default)" if default and name == default else ""
        print(f"    [{i}]  {name}{marker}")
    print()
    print("  Enter a number, type a name, or press Enter for default.")
    print("=" * 44)

    while True:
        try:
            raw = input("\nYour choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)

        if not raw:
            if allow_default and default and default in names:
                print(f"Using default: {default}")
                return default
            print("Please enter a number or name.")
            continue

        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(names):
                chosen = names[idx - 1]
                print(f"Locking onto: {chosen}")
                return chosen
            print(f"Enter a number between 1 and {len(names)}.")
            continue

        # Match by name (case-insensitive)
        matches = [n for n in names if n.lower() == raw.lower()]
        if len(matches) == 1:
            print(f"Locking onto: {matches[0]}")
            return matches[0]

        partial = [n for n in names if raw.lower() in n.lower()]
        if len(partial) == 1:
            print(f"Locking onto: {partial[0]}")
            return partial[0]

        print(f"Unknown speaker '{raw}'. Pick from: {', '.join(names)}")


def resolve_target_name(
    cli_name: Optional[str],
    *,
    pick: bool = False,
    default: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> str:
    """
    Resolve target speaker for CLI tools.
    - --name X without --pick  → use X (must exist in DB)
    - no --name or --pick      → interactive menu
    """
    path = db_path or default_db_path()
    names = list_enrolled_speakers(path)

    if not names:
        print(f"\nERROR: No enrolled speakers in {path}")
        sys.exit(1)

    if cli_name and not pick:
        if cli_name not in names:
            print(f"\nWARNING: '{cli_name}' is not in the database.")
            print(f"Enrolled speakers: {', '.join(names)}")
            print("Opening speaker selection...\n")
            return prompt_select_speaker(path, default=default or names[0])
        return cli_name

    return prompt_select_speaker(path, default=default or cli_name or (names[0] if names else None))
