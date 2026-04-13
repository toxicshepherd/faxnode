@echo off
REM FaxNode Client – Windows-Exe bauen
REM Voraussetzung: Python 3.10+ mit pip
echo FaxNode Client wird gebaut...
pip install pywebview pyinstaller
pyinstaller --onefile --noconsole --name "FaxNode" --hidden-import clr --hidden-import webview faxnode_client.py
echo.
echo Fertig: dist\FaxNode.exe
pause
