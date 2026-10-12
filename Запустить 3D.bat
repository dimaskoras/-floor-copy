@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto fail
  ".venv\Scripts\python.exe" -m pip install -r desktop\requirements.txt
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" desktop\launcher.py start
if errorlevel 1 goto fail
exit /b 0
:fail
echo Не удалось запустить 3D. Посмотри сообщение выше.
pause
