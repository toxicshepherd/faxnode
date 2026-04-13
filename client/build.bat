@echo off
REM FaxNode Client – Lokal bauen
REM Voraussetzung: Python 3.10+, Inno Setup
echo [1/2] Exe wird gebaut...
pip install pywebview pyinstaller
pyinstaller --onefile --noconsole --name "FaxNode" --hidden-import clr --hidden-import webview faxnode_client.py
echo.
echo [2/2] Installer wird gebaut...
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer.iss
    echo.
    echo Fertig: output\FaxNode-Setup.exe
) else (
    echo Inno Setup nicht gefunden — nur Exe gebaut: dist\FaxNode.exe
    echo Installer: https://jrsoftware.org/isinfo.php
)
pause
