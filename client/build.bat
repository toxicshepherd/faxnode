@echo off
REM FaxNode Client – Windows-Exe bauen
REM Voraussetzung: Python 3.10+ mit pip
echo FaxNode Client wird gebaut...
pip install pyinstaller
pyinstaller --onefile --noconsole --name "FaxNode" --icon "faxnode.ico" faxnode_client.py
echo.
echo Fertig: dist\FaxNode.exe
pause
