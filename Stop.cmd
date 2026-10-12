@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" desktop\launcher.py stop
if errorlevel 1 pause
