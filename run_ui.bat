@echo off
cd /d "C:\Users\avmaa\Downloads\nebula-ops-agent\nebula-ops-agent"
start "Nebula Kirana Ops UI" cmd /k "cd /d ""C:\Users\avmaa\Downloads\nebula-ops-agent\nebula-ops-agent"" && ""C:\Users\avmaa\AppData\Local\Programs\Python\Python311\python.exe"" ui_app.py"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline = (Get-Date).AddSeconds(15); do { try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5000/' -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep -Milliseconds 250 } } while ((Get-Date) -lt $deadline)"
start "" http://127.0.0.1:5000
