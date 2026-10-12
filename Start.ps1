$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать окружение Python. Нужен Python 3.11 или новее.' }
    & $pythonPath -m pip install -r desktop\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить библиотеки.' }
}
Start-Process 'http://127.0.0.1:4318'
& $pythonPath desktop\server.py
