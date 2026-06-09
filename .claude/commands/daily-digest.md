---
description: Fetch latest feeds, rank against my profile, email the top picks, commit & push.
---

Run the full daily digest pipeline. Be efficient — minimize redundant reads.

## Step 0: Ensure dependencies (cloud routine only)

If running in a fresh cloud routine environment, install Python deps first:

```
pip install -r requirements.txt
```

If running locally on Chuchen's Windows machine, dependencies are already there — skip.

## Step 1: Fetch the latest data

Run the fetcher with a 24h lookback:

```
python fetch.py 24
```

If fetch fails entirely, stop and report the error. If individual feeds fail (printed as `[error]` / `[warn]`), continue — partial data is fine.

## Step 2: Extract today's items into a compact JSON

```
python pick_today.py 24
```

This writes `tmp_today.json` containing only items added in the last 24h, with just the fields you need: `url, title, source, type, summary, date, date_iso`.

If `tmp_today.json` has zero items, **do not** send an empty email — just print "No new items today, skipping email" and stop. (Still do the git commit so data.json stays in sync with the remote.)

## Step 3: Read profile + items

Read these two files:
- `profile.md` (the reader profile + scoring rubric)
- `tmp_today.json` (today's items)

## Step 4: Rank

For each item in `tmp_today.json`, decide:
- A **score** 0-10, calibrated to the rubric in `profile.md`
- A **one-sentence "why you'd care"** that is concrete and specific — what's the actual insight or angle, not "this is about AI agents". If the title alone makes the value obvious, you can frame the angle instead (e.g., "Direct evidence on whether reranker X beats reranker Y on the task you're working on").

**Be honest about scores.** Most items should land in the 3-6 range. Only items that genuinely hit the rubric's top tier deserve 8+. Filter out items with score < 5 entirely — they will not appear in the email.

## Step 5: Write picks file

**Group by type, then within each group keep the top 10 by score** (drop the rest). Types use the `type` field already on each item (`youtube`, `blog`, `twitter`, etc.).

The email template will display the groups in this order: Videos → Blogs → Podcasts → Papers → X/Twitter. So if you only have 3 videos and 8 blogs, the email shows 3 + 8 = 11 items total. **There is no global cap** — caps are per-category.

Concatenate all kept items into one flat list (any order is fine; `send_email.py` re-groups and re-sorts). Write to `picks/YYYY-MM-DD.json` (today's date, UTC):

```json
[
  {
    "url": "...",
    "title": "...",
    "source": "...",
    "type": "...",
    "summary": "...",
    "date": "...",
    "score": 9,
    "why": "..."
  }
]
```

Create the `picks/` directory if it doesn't exist.

## Step 6: Send the email

```
python send_email.py picks/YYYY-MM-DD.json
```

The script uses Resend's HTTP API (Anthropic CCR sandboxes block SMTP outbound, so Gmail SMTP does not work). It needs `RESEND_API_KEY` in the environment and defaults the recipient to `sysuxcc@gmail.com`. Pass `DIGEST_SCANNED_TOTAL=<n>` so the email header can show "top X of N scanned".

Linux / cloud routine — pass env vars inline in one Bash call:
```
RESEND_API_KEY='re_xxx' DIGEST_SCANNED_TOTAL=<count> python send_email.py picks/YYYY-MM-DD.json
```

Windows PowerShell (local):
```
$env:RESEND_API_KEY = 're_xxx'
$env:DIGEST_SCANNED_TOTAL = '<count>'
python send_email.py picks/YYYY-MM-DD.json
```

If `RESEND_API_KEY` is missing or still a placeholder, stop and report — do not try to send.

## Step 7: Commit & push to main

```
git add data.json picks/
git commit -m "daily digest YYYY-MM-DD ($N picks of $TOTAL scanned)"
git push origin HEAD:main
```

**Push directly to `main`** — do NOT create a feature branch or PR. This is a state-sync commit (just dedup state + pick archive), not a code change, so it must land on `main` to be visible to the next day's run. If your sandbox environment opens you on a feature branch by default, `git push origin HEAD:main` forces the push to land on `main` regardless.

If there's nothing to commit (no new items, no data.json change), skip the commit.

## Final report

Print a short summary: total scanned, kept after filter, top 3 titles with scores, email sent / skipped.
