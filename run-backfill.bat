@echo off
echo Running backfill (last 30 days)...
"C:\Users\sysux\AppData\Local\Programs\Python\Python311\python.exe" "%~dp0fetch.py" 720
echo Done.
pause
