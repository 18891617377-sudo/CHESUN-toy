@echo off
chcp 65001 >nul
title Build WinCage
cd /d "%~dp0"
set PY=C:\Users\18891\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

echo === check PyInstaller ===
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo installing PyInstaller...
  "%PY%" -m pip install pyinstaller --quiet
)

echo === build single EXE ===
"%PY%" -m PyInstaller --noconfirm --onefile --windowed ^
  --name WinCage ^
  --icon "app.ico" ^
  --add-data "README.txt;." ^
  --add-data "app.ico;." ^
  main.py

echo === result ===
if exist "dist\WinCage.exe" (
  echo OK: dist\WinCage.exe
  for %%F in ("dist\WinCage.exe") do echo size=%%~zF bytes
) else (
  echo BUILD FAILED
)
pause
