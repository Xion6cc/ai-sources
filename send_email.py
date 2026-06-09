#!/usr/bin/env python3
"""Send the daily AI digest email from a picks JSON file.

Usage:
    python send_email.py picks/2026-06-08.json

Picks JSON schema (list of objects, already sorted by score desc):
    [
      {
        "url":     "...",
        "title":   "...",
        "source":  "...",
        "type":    "youtube|blog|twitter|...",
        "date":    "2026-06-08 09:00 UTC",
        "summary": "...",   (optional, original feed excerpt)
        "score":   9,
        "why":     "one-line reason this matters to me"
      },
      ...
    ]

Env vars required:
    GMAIL_USER          e.g. sysuxcc@gmail.com
    GMAIL_APP_PASSWORD  16-char app password from myaccount.google.com
Optional:
    DIGEST_TO           recipient (defaults to GMAIL_USER)
    DIGEST_SCANNED_TOTAL  number of items scanned today (for the "of N" line)
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE_DIR      = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Section display order + labels + colors. Keys are item["type"] values from data.json.
SECTION_DEFS = [
    {"type": "youtube", "label": "Videos",  "label_short": "videos",  "color": "#ff4444"},
    {"type": "blog",    "label": "Blogs",   "label_short": "blogs",   "color": "#4488ff"},
    {"type": "podcast", "label": "Podcasts","label_short": "podcasts","color": "#22d3a0"},
    {"type": "paper",   "label": "Papers",  "label_short": "papers",  "color": "#f59e42"},
    {"type": "twitter", "label": "X / Twitter", "label_short": "tweets", "color": "#1a1a1a"},
]


def group_into_sections(picks: list[dict]) -> list[dict]:
    """Bucket picks by type into the display sections (sorted by score desc within each)."""
    buckets = {s["type"]: [] for s in SECTION_DEFS}
    leftover_types: dict[str, list] = {}
    for p in picks:
        t = p.get("type", "blog")
        if t in buckets:
            buckets[t].append(p)
        else:
            leftover_types.setdefault(t, []).append(p)

    sections = []
    for s in SECTION_DEFS:
        items = sorted(buckets[s["type"]], key=lambda x: x.get("score", 0), reverse=True)
        sections.append({**s, "entries": items})

    # Any unknown types get a generic section at the end so nothing silently disappears
    for t, leftover in leftover_types.items():
        sections.append({
            "type": t, "label": t.capitalize(), "label_short": t,
            "color": "#888",
            "entries": sorted(leftover, key=lambda x: x.get("score", 0), reverse=True),
        })

    return sections


def render(picks: list[dict], date: str, scanned_total: int) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    return env.get_template("email.html").render(
        date=date,
        sections=group_into_sections(picks),
        scanned_total=scanned_total,
    )


def send(html: str, subject: str, sender: str, recipient: str, password: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.login(sender, password)
        s.send_message(msg)


def main():
    if len(sys.argv) < 2:
        print("Usage: python send_email.py <picks.json>", file=sys.stderr)
        sys.exit(2)

    picks_path = Path(sys.argv[1])
    picks = json.loads(picks_path.read_text(encoding="utf-8"))

    sender    = os.environ["GMAIL_USER"]
    password  = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("DIGEST_TO", sender)
    scanned   = int(os.environ.get("DIGEST_SCANNED_TOTAL", 0))

    # Date from the picks filename if it matches YYYY-MM-DD, else today
    date = picks_path.stem if len(picks_path.stem) == 10 and picks_path.stem[4] == "-" \
           else datetime.now().strftime("%Y-%m-%d")

    subject = f"AI Digest {date} — top {len(picks)} picks"
    html    = render(picks, date, scanned)
    send(html, subject, sender, recipient, password)
    print(f"Sent {len(picks)} picks to {recipient}")


if __name__ == "__main__":
    main()
