#!/usr/bin/env python3
"""Rank today's items against profile.md using Gemini 2.5 Flash, write picks JSON.

Reads:
    tmp_today.json   (output of pick_today.py — last-24h items)
    profile.md       (reader interest rubric)

Writes:
    picks/YYYY-MM-DD.json   (today's UTC date), containing only items with score >= 5,
                            capped at top 10 per type, flat list (send_email.py regroups).

Env vars:
    GEMINI_API_KEY  required
    GEMINI_MODEL    optional (default: gemini-2.5-flash)

Why Gemini Flash: free tier covers daily use (well under 250 req/day),
and we already have a key in summarize.py. Anthropic API would also work
but is metered.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR    = Path(__file__).parent
TODAY_FILE  = BASE_DIR / "tmp_today.json"
PROFILE     = BASE_DIR / "profile.md"
PICKS_DIR   = BASE_DIR / "picks"

GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"

MIN_SCORE   = 5
TOP_PER_TYPE = 10


PROMPT_TEMPLATE = """\
You are ranking AI/tech content items for a specific reader. Read the reader's
interest rubric, then assign each item a score (0-10) and a one-sentence
"why you'd care" line.

# READER RUBRIC
{profile}

# ITEMS TO SCORE
A JSON array of items follows. Each has: url, title, source, type, summary.

{items}

# YOUR OUTPUT
Return ONLY a JSON array (no markdown fences, no prose), one entry per input
item, in the SAME order, with this exact shape:

[
  {{
    "url": "<copy from input>",
    "score": <integer 0-10>,
    "why": "<one specific sentence — what insight or angle would this give the reader, NOT a generic 'this is about X'>"
  }},
  ...
]

Calibration:
- 9-10: directly hits the rubric's top tier with real engineering depth.
- 7-8: solid relevance, would read it.
- 5-6: tangential interest, might skim.
- 0-4: filter list — hype, off-topic, surface-level.

Be honest. Most items should be 3-6. Reserve 8+ for items that clearly match
the top-tier description in the rubric. Items scoring below 5 will be dropped
from the email, so do not inflate to keep them.

The "why" sentence must be specific to THIS item — name the concrete insight,
not the topic.
"""


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    url = f"{GEMINI_URL}/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API error {e.code}: {msg}") from e

    return payload["candidates"][0]["content"]["parts"][0]["text"]


def parse_scores(raw: str) -> list[dict]:
    """Parse Gemini's response. With responseMimeType=application/json it's pure JSON."""
    raw = raw.strip()
    # Defensive: strip code fences if the model added them despite the JSON mime type
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
    return json.loads(raw)


def cap_per_type(picks: list[dict]) -> list[dict]:
    """Within each type bucket, keep only the top N by score."""
    buckets: dict[str, list] = {}
    for p in picks:
        buckets.setdefault(p["type"], []).append(p)
    result = []
    for items in buckets.values():
        items.sort(key=lambda x: x["score"], reverse=True)
        result.extend(items[:TOP_PER_TYPE])
    return result


def main():
    api_key = os.environ["GEMINI_API_KEY"]
    model   = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

    items = json.loads(TODAY_FILE.read_text(encoding="utf-8"))
    if not items:
        print("No items to rank; skipping picks file.")
        sys.exit(0)

    profile = PROFILE.read_text(encoding="utf-8")

    prompt = PROMPT_TEMPLATE.format(
        profile=profile,
        items=json.dumps(items, ensure_ascii=False, indent=2),
    )

    print(f"Calling {model} to score {len(items)} item(s) ...")
    raw_response = call_gemini(prompt, api_key, model)
    scores = parse_scores(raw_response)

    if len(scores) != len(items):
        print(f"[warn] model returned {len(scores)} scores for {len(items)} items; matching by url")

    # Merge scores back onto the original items (by url, robust to reordering)
    by_url = {s["url"]: s for s in scores}
    picks = []
    for it in items:
        s = by_url.get(it["url"])
        if not s:
            print(f"[warn] no score for {it['url'][:70]}")
            continue
        if s["score"] < MIN_SCORE:
            continue
        picks.append({**it, "score": int(s["score"]), "why": s["why"]})

    picks = cap_per_type(picks)

    PICKS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = PICKS_DIR / f"{today}.json"
    out_path.write_text(json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8")

    kept_by_type: dict[str, int] = {}
    for p in picks:
        kept_by_type[p["type"]] = kept_by_type.get(p["type"], 0) + 1

    print(f"Scored {len(items)} items, kept {len(picks)} after filter (>= {MIN_SCORE}, top {TOP_PER_TYPE}/type)")
    for t, n in kept_by_type.items():
        print(f"  {t}: {n}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
