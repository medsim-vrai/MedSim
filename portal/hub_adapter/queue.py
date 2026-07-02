"""Durable local-bridge spool for V8 (offline-tolerant, no-loss).

Each event is written as one JSON file named by a monotonic sequence + event_id, so
order is preserved and a restart simply re-reads the directory. `replay(sender)`
sends pending events in order and deletes each only on a successful ack — so a crash
or network drop loses nothing and (with the consumer de-duplicating on event_id)
delivers exactly once. Mirrors the platform's append-only / no-data-loss rule."""
from __future__ import annotations
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


class Spool:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _seq(self) -> int:
        # microsecond clock keeps global order across restarts; collisions broken by event_id
        return int(time.time() * 1_000_000)

    def enqueue(self, evt: dict[str, Any]) -> Path:
        name = f"{self._seq():020d}-{evt['event_id']}.json"
        path = self.dir / name
        # atomic write: temp file + rename, so a crash never leaves a half-written event
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(evt, f, separators=(",", ":"))
        os.replace(tmp, path)
        return path

    def pending(self) -> list[Path]:
        return sorted(p for p in self.dir.glob("*.json"))

    def depth(self) -> int:
        return len(self.pending())

    def replay(self, sender: Callable[[dict[str, Any]], bool]) -> int:
        """Send pending events in order. Stop at the first failure (retry next time).
        Returns the count successfully acked + removed."""
        sent = 0
        for path in self.pending():
            try:
                evt = json.loads(path.read_text())
            except Exception:
                path.unlink(missing_ok=True)        # corrupt file: drop + move on (logged upstream)
                continue
            try:
                ok = sender(evt)
            except Exception:
                break                                # offline / error: keep file, retry later
            if not ok:
                break
            path.unlink(missing_ok=True)             # ack: safe to remove now
            sent += 1
        return sent
