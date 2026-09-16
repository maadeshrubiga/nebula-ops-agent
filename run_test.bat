@echo off
cd /d "C:\Users\avmaa\Downloads\nebula-ops-agent\nebula-ops-agent"
"C:\Users\avmaa\AppData\Local\Programs\Python\Python311\python.exe" -m tests.test_flow
if errorlevel 1 (
    echo.
    echo Test exited with an error. Press any key to close this window...
    pause >nul
)
