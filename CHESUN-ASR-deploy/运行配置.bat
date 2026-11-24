@echo off
rem CHESUN ASR runner: keep this bat next to the ps1, double-click to run
for /f "delims=" %%f in ('dir /b /a-d "%~dp0CHESUN*ASR*.ps1"') do set "TARGET=%~dp0%%f"
if not defined TARGET echo Script not found.
powershell -NoProfile -ExecutionPolicy Bypass -File "%TARGET%"
