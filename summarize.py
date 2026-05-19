#!/usr/bin/env python3
"""Fetch YouTube transcripts and summarize via Gemini for items in data.json."""

import json
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

BASE_DIR      = Path(__file__).parent
DATA_FILE     = BASE_DIR / "data.json"
REPORTS_DIR   = BASE_DIR / "reports"
TEMPLATES_DIR = BASE_DIR / "templates"

GEMINI_API_KEY = "AIzaSyArrmrgBvdfON7sDXz4lXwYzpLrYmIxDBk"
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MAX_TRANSCRIPT_CHARS = 100000  # Gemini Flash handles large contexts easily

SUPADATA_API_KEY = "sd_5883d5a6026a30897ada45b3632cf9c2"
SUPADATA_URL     = "https://api.supadata.ai/v1/youtube/transcript"


# ---------------------------------------------------------------------------
# Transcript via Supadata
# ---------------------------------------------------------------------------

def get_transcript(video_url: str) -> str:
    """Return plain-text transcript via Supadata API."""
    params = urllib.parse.urlencode({"url": video_url, "text": "true"})
    req = urllib.request.Request(
        f"{SUPADATA_URL}?{params}",
        headers={
            "x-api-key": SUPADATA_API_KEY,
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            content = data.get("content", "")
            if isinstance(content, str):
                return content.strip()
            # fallback: content is a list of segments
            return " ".join(seg.get("text", "") for seg in content).strip()
    except Exception as e:
        print(f"    [warn] Supadata error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def gemini_summarize(transcript: str, title: str) -> str:
    """Send transcript to Gemini Flash and return a summary string."""
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "..."

    prompt = (
        f"You are summarizing a YouTube video for an AI/ML engineer audience.\n\n"
        f"Video title: {title}\n\n"
        f"Transcript:\n{transcript}\n\n"
        f"Write a concise summary in 3-5 sentences covering: what the video is about, "
        f"the key insights or takeaways, and why it matters for AI/ML practitioners. "
        f"Be direct and specific. No filler phrases."
    )

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode()

    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    [error] Gemini request failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Report regeneration
# ---------------------------------------------------------------------------

def regenerate_report(items: list[dict]) -> None:
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item["type"], []).append(item)

    REPORTS_DIR.mkdir(exist_ok=True)
    env      = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("report.html")
    html     = template.render(date=today, groups=groups, total=len(items))

    report_path = REPORTS_DIR / "digest.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"Report updated: {report_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not DATA_FILE.exists():
        print("No data.json found. Run fetch.py first.")
        return

    with open(DATA_FILE, encoding="utf-8") as f:
        items = json.load(f)

    youtube_items = [it for it in items if it.get("type") == "youtube"]
    pending = [it for it in youtube_items if not it.get("transcript_summary")]

    print(f"YouTube items total:    {len(youtube_items)}")
    print(f"Pending summarization:  {len(pending)}")

    if not pending:
        print("All YouTube items already have summaries.")
        return

    updated = 0
    for i, item in enumerate(pending):
        title = item["title"]
        print(f"\n  [{i + 1}/{len(pending)}] {title[:70]}")

        print("    Getting transcript...")
        transcript = get_transcript(item["url"])
        if not transcript:
            print("    No transcript available, skipping.")
            item["transcript_summary"] = None  # mark as attempted
            continue

        item["transcript"] = transcript  # save full transcript

        if i > 0:
            import time
            time.sleep(13)  # stay under 5 RPM free tier limit (gemini-2.5-flash)

        print(f"    Transcript: {len(transcript)} chars. Summarizing with Gemini Flash...")
        summary = gemini_summarize(transcript, title)
        if summary:
            item["transcript_summary"] = summary
            print(f"    Done: {summary[:80]}...")
            updated += 1
        else:
            item["transcript_summary"] = None

    # Save updated data.json
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"\nSummarized {updated} new item(s).")

    # Regenerate report
    regenerate_report(items)

    import webbrowser
    webbrowser.open((REPORTS_DIR / "digest.html").as_uri())


if __name__ == "__main__":
    main()
