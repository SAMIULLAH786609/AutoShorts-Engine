@echo off
cd /d "c:\Users\786mu\OneDrive\Attachments\Desktop\AutoShorts-Engine"
echo ============================================
echo  AutoShorts Engine - Auto Daily Upload
echo  Starting: %date% %time%
echo ============================================
call .venv\Scripts\activate.bat
python run.py
echo ============================================
echo  Finished: %date% %time%
echo ============================================
