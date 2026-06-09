#!/usr/bin/env python3
"""Extract today's new items from data.json into a compact JSON file for the ranker.

Writes to tmp_today.json (gitignored). Strips fields the ranker doesn't need
(thumbnail_url, note_path, transcript) so the LLM context stays small.

Default window: 24 hours back from now. Override with first CLI arg in hours.
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
OUT_FILE  = BASE_DIR / "tmp_today.json"

KEEP_FIELDS = ("url", "title", "source", "type", "summary", "date", "date_iso")


def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    items = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    today = []
    for it in items:
        iso = it.get("date_iso", "")
        if not iso:
            continue
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt >= cutoff:
            today.append({k: it[k] for k in KEEP_FIELDS if k in it})

    OUT_FILE.write_text(json.dumps(today, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(today)} item(s) in the last {hours}h -> {OUT_FILE.name}")


if __name__ == "__main__":
    main()
