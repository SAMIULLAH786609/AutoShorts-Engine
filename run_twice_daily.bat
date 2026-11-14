@echo off
:: AutoShorts Engine — Windows Task Scheduler trigger
:: Add this to Windows Task Scheduler to run twice daily.
:: The .env UPLOAD_TIME_1 / UPLOAD_TIME_2 variables control exact times
:: when running in --schedule mode. This bat file triggers a one-shot run.

cd /d "%~dp0"

call .venv\Scripts\activate

python run.py >> logs\scheduler.log 2>&1
