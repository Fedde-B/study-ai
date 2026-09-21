$ErrorActionPreference = 'Stop'
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    py -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
}
.venv\Scripts\python.exe app.py
