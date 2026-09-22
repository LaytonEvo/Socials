"""Append-only JSONL run log.

One line per event, flushed immediately. A spike that crashes halfway must
still leave behind everything it learned before it died -- including how much
it had already spent.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path
from typing import Any


def new_run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


class RunLog:
    """Events for one spike run, under ``<run_root>/<run_id>/``."""

    def __init__(self, run_dir: Path | str) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "run.jsonl"
        self.path.touch()

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    def event(self, kind: str, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "run_id": self.run_id,
            "kind": kind,
        }
        record.update(fields)
        line = json.dumps(record, default=str, sort_keys=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return record

    def read(self, kind: str | None = None) -> list[dict[str, Any]]:
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if kind is None or rec.get("kind") == kind:
                out.append(rec)
        return out

    def write_artifact(self, name: str, payload: Any) -> Path:
        """Write a JSON artifact next to the log and record that it exists."""
        dest = self.run_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        self.event("artifact", name=name, path=str(dest))
        return dest
