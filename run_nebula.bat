@echo off
cd /d "C:\Users\avmaa\Downloads\nebula-ops-agent\nebula-ops-agent"
"C:\Users\avmaa\AppData\Local\Programs\Python\Python311\python.exe" run_bot.py
if errorlevel 1 (
    echo.
    echo Bot exited with an error. Press any key to close this window...
    pause >nul
)
