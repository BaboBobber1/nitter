#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'

$root = Split-Path -Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent
Set-Location $root

if (-not (Test-Path '.venv')) {
    python -m venv .venv
}

$venvActivate = Join-Path $root '.venv/Scripts/Activate.ps1'
. $venvActivate
python -m pip install --upgrade pip | Out-Null
pip install -r backend/requirements.txt | Out-Null

$env:FLASK_APP = 'backend.app'
$env:HOST = $env:HOST -or '127.0.0.1'
$env:PORT = $env:PORT -or '5173'

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    $url = "http://$env:HOST`:$env:PORT"
    $browsers = @('chrome', 'msedge', 'chromium')
    foreach ($browser in $browsers) {
        try {
            Start-Process $browser $url
            return
        } catch {
        }
    }
    Start-Process $url
} | Out-Null

flask run --host $env:HOST --port $env:PORT
