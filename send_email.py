#!/usr/bin/env python3
"""Send the daily AI digest email via Resend's HTTP API.

We use Resend (https://resend.com) instead of Gmail SMTP because:
- Cloud sandboxes (Anthropic CCR routines, AWS, GCP, etc.) block outbound
  SMTP ports (25 / 465 / 587) by default — a long-standing anti-spam measure.
- Resend's API is plain HTTPS POST to api.resend.com:443, which sandboxes
  always allow. Resend then handles the actual SMTP delivery on its side.
- Resend's free tier (3,000 emails/month) easily covers daily personal use,
  and self-to-self sends do not require a verified domain — they accept
  the default `onboarding@resend.dev` sender.

Usage:
    python send_email.py picks/2026-06-09.json

Env vars:
    RESEND_API_KEY       required — your Resend API key (starts with `re_`)
    DIGEST_TO            optional — recipient email (default: sysuxcc@gmail.com)
    DIGEST_FROM          optional — sender (default: "AI Digest <onboarding@resend.dev>")
    DIGEST_SCANNED_TOTAL optional — total items scanned today (for the email header)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE_DIR      = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

RESEND_URL   = "https://api.resend.com/emails"
DEFAULT_TO   = "sysuxcc@gmail.com"
DEFAULT_FROM = "AI Digest <onboarding@resend.dev>"

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


def send(html: str, subject: str, sender: str, recipient: str, api_key: str) -> dict:
    body = json.dumps({
        "from":    sender,
        "to":      [recipient],
        "subject": subject,
        "html":    html,
    }).encode("utf-8")

    req = urllib.request.Request(
        RESEND_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API error {e.code}: {msg}") from e


def main():
    if len(sys.argv) < 2:
        print("Usage: python send_email.py <picks.json>", file=sys.stderr)
        sys.exit(2)

    picks_path = Path(sys.argv[1])
    picks = json.loads(picks_path.read_text(encoding="utf-8"))

    api_key   = os.environ["RESEND_API_KEY"]
    sender    = os.environ.get("DIGEST_FROM", DEFAULT_FROM)
    recipient = os.environ.get("DIGEST_TO",   DEFAULT_TO)
    scanned   = int(os.environ.get("DIGEST_SCANNED_TOTAL", 0))

    date = picks_path.stem if len(picks_path.stem) == 10 and picks_path.stem[4] == "-" \
           else datetime.now().strftime("%Y-%m-%d")

    subject = f"AI Digest {date} — top {len(picks)} picks"
    html    = render(picks, date, scanned)
    result  = send(html, subject, sender, recipient, api_key)
    print(f"Sent {len(picks)} picks to {recipient} (resend id: {result.get('id', '?')})")


if __name__ == "__main__":
    main()
