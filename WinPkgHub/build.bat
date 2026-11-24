@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pyinstaller >nul 2>nul
if errorlevel 1 (
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name WinPkgHub main.py
) else (
    pyinstaller --noconfirm --clean --onefile --windowed --name WinPkgHub main.py
)
echo.
echo 输出：dist\WinPkgHub.exe
pause
