---
description: Run the full daily digest pipeline locally (same scripts as the GitHub Action).
---

This is the local invocation of the pipeline that normally runs as a GitHub Actions cron (`.github/workflows/daily-digest.yml`). Useful for manual re-runs and debugging. Steps are identical to the workflow — fetch → extract → rank → email → commit.

## Prerequisites

Set these env vars in your shell before running:

```powershell
$env:GEMINI_API_KEY = '...'         # for ranking
$env:RESEND_API_KEY = 're_...'      # for email
```

(In the GitHub Actions environment these come from repo secrets.)

## Steps

Run these in order, stopping on error:

1. **Fetch** — `python fetch.py 24`
2. **Extract today's items** — `python pick_today.py 24`
3. **Rank** — `python rank.py` (calls Gemini, writes `picks/YYYY-MM-DD.json`)
4. **Email** — figure out today's UTC date and the count:
   ```powershell
   $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
   $scanned = (Get-Content tmp_today.json | ConvertFrom-Json).Count
   $env:DIGEST_SCANNED_TOTAL = "$scanned"
   python send_email.py "picks/$today.json"
   ```
5. **Commit & push** — `git add data.json picks/ && git commit -m "daily digest $today" && git push origin HEAD:main`

If step 2 produces zero items, skip steps 3-4 (nothing to email) but still do step 5 in case `data.json` itself was updated.

## Final report

Print a short summary: total scanned, kept after filter by category, top 3 titles with scores, email sent / skipped, commit hash pushed.
