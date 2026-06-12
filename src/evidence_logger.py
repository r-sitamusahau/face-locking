"""
BENAX assessment evidence logger.
Writes speaker ID, confidence, timestamp, and motor command to CSV + JSON.
Uses stdlib only (no pandas).
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class EvidenceRecord:
    timestamp: str
    speaker_id: str
    confidence: float
    motor_command: str
    locked: bool


class EvidenceLogger:
    def __init__(self, log_dir: Path | None = None):
        base = log_dir or Path(__file__).parent.parent / "data" / "logs"
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.csv_path = base / f"evidence_{stamp}.csv"
        self.json_path = base / f"evidence_{stamp}.json"
        self._records: list[EvidenceRecord] = []
        self._last_command: Optional[str] = None

        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "speaker_id", "confidence", "motor_command", "locked"])

        print(f"[Evidence] CSV  -> {self.csv_path}")
        print(f"[Evidence] JSON -> {self.json_path}")

    def log(
        self,
        speaker_id: str,
        confidence: float,
        motor_command: str,
        locked: bool,
        *,
        force: bool = False,
    ) -> None:
        """Append row when command changes or on forced events (lock/search)."""
        if not force and motor_command == self._last_command:
            return

        self._last_command = motor_command
        record = EvidenceRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            speaker_id=speaker_id or "",
            confidence=round(float(confidence), 4),
            motor_command=motor_command,
            locked=bool(locked),
        )
        self._records.append(record)

        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    record.timestamp,
                    record.speaker_id,
                    record.confidence,
                    record.motor_command,
                    record.locked,
                ]
            )

        self.json_path.write_text(
            json.dumps([asdict(r) for r in self._records], indent=2),
            encoding="utf-8",
        )
