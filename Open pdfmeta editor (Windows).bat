@echo off
rem Double-click this file to open the pdfmeta metadata editor in your browser.
cd /d "%~dp0"
python -c "import pdfmeta, flask" 2>nul || python -m pip install -e ".[gui]"
echo Opening the editor in your browser... keep this window open while you work.
python -m pdfmeta gui
pause
