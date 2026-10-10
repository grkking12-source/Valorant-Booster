@echo off
cd /d "%~dp0"
echo Installing build tools (first time takes a few minutes)...
python -m pip install pyinstaller PySide6 psutil
echo.
echo Building ValorantOptimizer.exe ...
python -m PyInstaller --noconfirm --clean --noconsole --name ValorantOptimizer app.py
xcopy /E /I /Y config dist\ValorantOptimizer\config >nul
echo.
echo DONE. Open this folder and double-click ValorantOptimizer.exe:
echo   %cd%\dist\ValorantOptimizer
pause
