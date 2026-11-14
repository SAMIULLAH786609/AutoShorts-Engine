@echo off
cd /d "%~dp0"
echo ============================================
echo  AutoShorts Engine - Auto Daily Upload
echo  Starting: %date% %time%
echo ============================================
call .venv\Scripts\activate.bat
python run.py
echo ============================================
echo  Finished: %date% %time%
echo ============================================
