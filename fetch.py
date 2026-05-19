#!/usr/bin/env python3
"""AI News Digest — fetch feeds and generate cumulative report."""

import json
import re
import sys
import yaml
import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin
from jinja2 import Environment, FileSystemLoader


class AttrDict(dict):
    """Dict that supports attribute access — used to mimic feedparser entries for scraped sources."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR      = Path(__file__).parent
FEEDS_FILE    = BASE_DIR / "feeds.yaml"
NOTES_DIR     = BASE_DIR / "notes"
REPORTS_DIR   = BASE_DIR / "reports"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_FILE     = BASE_DIR / "data.json"

LOOKBACK_HOURS = int(sys.argv[1]) if len(sys.argv) > 1 else 24
EXCERPT_WORDS  = 60

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_feeds() -> list[dict]:
    with open(FEEDS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


def load_existing_items() -> dict[str, dict]:
    """Load accumulated items from data.json, keyed by URL."""
    if not DATA_FILE.exists():
        return {}
    with open(DATA_FILE, encoding="utf-8") as f:
        items = json.load(f)
    return {item["url"]: item for item in items}


def save_items(items_by_url: dict[str, dict]) -> None:
    items = sorted(items_by_url.values(), key=lambda x: x.get("date_iso", ""), reverse=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def entry_published(entry) -> datetime | None:
    """Return UTC-aware datetime for a feed entry, or None."""
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text.strip())
    return text[:80]


def extract_excerpt(entry) -> str:
    """Pull the feed's own description/summary, strip HTML, trim to N words."""
    raw = entry.get("summary", "")
    if not raw:
        content = entry.get("content", [])
        raw = content[0].get("value", "") if content else ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > EXCERPT_WORDS:
        text = " ".join(words[:EXCERPT_WORDS]) + " …"
    return text


def extract_feed_image(entry) -> str:
    """Try to find a thumbnail/image URL embedded in the RSS entry."""
    for m in entry.get("media_content", []):
        url = m.get("url", "")
        if url and m.get("medium", "") in ("image", "") and url.startswith("http"):
            return url

    for m in entry.get("media_thumbnail", []):
        url = m.get("url", "")
        if url and url.startswith("http"):
            return url

    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image/"):
            url = enc.get("href", enc.get("url", ""))
            if url:
                return url

    raw = entry.get("summary", "")
    if not raw:
        content = entry.get("content", [])
        raw = content[0].get("value", "") if content else ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw, re.IGNORECASE)
    if m:
        url = m.group(1)
        if url.startswith("http"):
            return url

    return ""


def write_note(item: dict) -> Path:
    NOTES_DIR.mkdir(exist_ok=True)
    fname = f"{item['date_str']}_{safe_filename(item['title'])}.md"
    path = NOTES_DIR / fname
    if path.exists():
        return path  # don't overwrite existing notes
    content = (
        f"# {item['title']}\n\n"
        f"- **Source:** {item['source']}\n"
        f"- **Date:** {item['date']}\n"
        f"- **URL:** {item['url']}\n"
        f"- **Excerpt:** {item['summary']}\n\n"
        f"---\n\n"
        f"## My Notes\n\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# HTML scraper fallback (for sites without RSS)
# ---------------------------------------------------------------------------

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def scrape_feed(url: str, cfg: dict) -> AttrDict:
    """Scrape an HTML page and return a feedparser-shaped result (.entries, .bozo)."""
    article_sel = cfg.get("article_selector", "article")
    title_sel   = cfg.get("title_selector", "h2, h3")
    date_sel    = cfg.get("date_selector", "time")
    summary_sel = cfg.get("summary_selector")
    link_sel    = cfg.get("link_selector")

    resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    entries = []
    for el in soup.select(article_sel):
        title_el = el.select_one(title_sel) if title_sel else el
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not title:
            continue

        link = ""
        if link_sel:
            a = el.select_one(link_sel)
            if a:
                link = a.get("href", "")
        elif el.name == "a":
            link = el.get("href", "")
        else:
            a = el.find("a", href=True)
            if a:
                link = a["href"]
        if not link:
            continue
        link = urljoin(url, link)

        published_parsed = None
        date_el = el.select_one(date_sel) if date_sel else None
        if date_el:
            raw = date_el.get("datetime") or date_el.get_text(strip=True)
            if raw:
                try:
                    dt = date_parser.parse(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    published_parsed = dt.astimezone(timezone.utc).timetuple()
                except (ValueError, TypeError, OverflowError):
                    pass

        summary = ""
        if summary_sel:
            sum_el = el.select_one(summary_sel)
            if sum_el:
                summary = sum_el.get_text(" ", strip=True)

        entries.append(AttrDict(
            title=title,
            link=link,
            summary=summary,
            published_parsed=published_parsed,
        ))

    return AttrDict(entries=entries, bozo=False, bozo_exception=None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    feeds  = load_feeds()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    today  = datetime.now().strftime("%Y-%m-%d")

    print(f"AI Digest — {today}")
    print(f"Fetching {len(feeds)} feed(s), looking back {LOOKBACK_HOURS}h ...")

    # Load accumulated items and prune anything older than 30 days
    existing = load_existing_items()
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
    pruned = {
        url: item for url, item in existing.items()
        if not item.get("date_iso") or datetime.fromisoformat(item["date_iso"].replace("Z", "+00:00")) >= cutoff_30d
    }
    if len(pruned) < len(existing):
        print(f"Pruned {len(existing) - len(pruned)} item(s) older than 30 days.")
    existing = pruned
    new_count = 0

    for feed_cfg in feeds:
        name  = feed_cfg["name"]
        url   = feed_cfg["url"]
        ftype = feed_cfg.get("type", "blog").lower()
        use_scraper = "scrape" in feed_cfg
        print(f"\n  [{ftype}{'/scrape' if use_scraper else ''}] {name}")

        try:
            if use_scraper:
                parsed = scrape_feed(url, feed_cfg["scrape"])
            else:
                parsed = feedparser.parse(url)
        except Exception as e:
            print(f"    [error] Could not fetch feed: {e}", file=sys.stderr)
            continue

        if parsed.bozo and not parsed.entries:
            print(f"    [warn] Feed parse error: {parsed.bozo_exception}", file=sys.stderr)
            continue

        filter_rt = feed_cfg.get("filter_retweets", False)
        feed_new = 0
        for entry in parsed.entries:
            pub = entry_published(entry)
            if pub and pub < cutoff:
                continue  # too old for this fetch window

            title = entry.get("title", "Untitled").strip()
            link  = entry.get("link", "")

            if not link:
                continue

            # Skip retweets and replies if requested
            if filter_rt and (title.startswith("RT by ") or title.startswith("R to ")):
                continue

            # Skip YouTube Shorts
            if ftype == "youtube" and "/shorts/" in link:
                continue

            # Skip if already accumulated
            if link in existing:
                continue

            # Thumbnail
            if ftype == "youtube":
                vid_match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", link)
                thumbnail_url = f"https://img.youtube.com/vi/{vid_match.group(1)}/mqdefault.jpg" if vid_match else ""
            else:
                thumbnail_url = extract_feed_image(entry)

            excerpt = extract_excerpt(entry)

            print(f"    + {title[:70]}")

            date_display = pub.strftime("%Y-%m-%d %H:%M UTC") if pub else "Unknown date"
            date_str     = pub.strftime("%Y-%m-%d") if pub else today
            date_iso     = pub.strftime("%Y-%m-%dT%H:%M:%SZ") if pub else ""

            item = {
                "title":         title,
                "url":           link,
                "source":        name,
                "type":          ftype,
                "summary":       excerpt,
                "date":          date_display,
                "date_str":      date_str,
                "date_iso":      date_iso,
                "thumbnail_url": thumbnail_url,
            }

            note_path = write_note(item)
            item["note_path"] = note_path.as_uri()

            existing[link] = item
            feed_new += 1
            new_count += 1

        print(f"    => {feed_new} new item(s)")

    # Persist accumulated data
    save_items(existing)

    all_items = sorted(existing.values(), key=lambda x: x.get("date_iso", ""), reverse=True)

    # Group by type
    groups: dict[str, list] = {}
    for item in all_items:
        groups.setdefault(item["type"], []).append(item)

    # Render HTML report
    REPORTS_DIR.mkdir(exist_ok=True)
    env      = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("report.html")
    html     = template.render(date=today, groups=groups, total=len(all_items))

    report_path = REPORTS_DIR / "digest.html"
    report_path.write_text(html, encoding="utf-8")

    print(f"\nNew items this run: {new_count}")
    print(f"Total accumulated:  {len(all_items)}")
    print(f"Report saved to:    {report_path}")

    import webbrowser
    webbrowser.open(report_path.as_uri())


if __name__ == "__main__":
    main()
