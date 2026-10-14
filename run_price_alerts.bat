@echo off
cd /d "%~dp0"
"C:\Python314\python.exe" price_alerts.py >> price_alerts.log 2>&1
