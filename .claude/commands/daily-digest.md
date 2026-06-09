---
description: Run the daily digest pipeline locally (same scripts as the GitHub Action).
---

This is the local invocation of the pipeline that normally runs as a GitHub Actions cron (`.github/workflows/daily-digest.yml`). Useful for manual re-runs and debugging.

## Prerequisites

Set this env var in your shell before running:

```powershell
$env:RESEND_API_KEY = 're_...'   # for email
```

## Steps

Run these in order, stopping on error:

1. **Fetch** — `python fetch.py 24`
2. **Extract today's items** — `python pick_today.py 24`
3. **Archive** —
   ```powershell
   $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
   New-Item -ItemType Directory -Force picks | Out-Null
   Copy-Item tmp_today.json "picks/$today.json"
   ```
4. **Email** —
   ```powershell
   $count = (Get-Content tmp_today.json | ConvertFrom-Json).Count
   if ($count -eq 0) { Write-Host "No items, skipping email."; return }
   $env:DIGEST_SCANNED_TOTAL = "$count"
   python send_email.py "picks/$today.json"
   ```
5. **Commit & push** — `git add data.json picks/ && git commit -m "daily digest $today" && git push origin HEAD:main`

## Final report

Print a short summary: items fetched, top 3 titles by section, email sent / skipped, commit hash pushed.
