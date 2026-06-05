"""The replayable decision log. Append-only newline-delimited JSON: one record per
entity-resolution decision, each carrying the full evidence vector and the threshold in
force, so any decision can be re-derived offline. The logs ARE the episode content.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path | None = None, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex
        self.records: list[dict] = []
        self._fh = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = p.open("a", encoding="utf-8")

    def log(self, action: str, **fields) -> dict:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "action": action,
            **fields,
        }
        self.records.append(record)
        if self._fh is not None:
            self._fh.write(json.dumps(record, sort_keys=True) + "\n")
            self._fh.flush()
        return record

    def replayable(self) -> list[dict]:
        """Records with run-specific noise (timestamp, run id) stripped — for diffing/replay."""
        return [{k: v for k, v in r.items() if k not in ("ts", "run_id")} for r in self.records]

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
