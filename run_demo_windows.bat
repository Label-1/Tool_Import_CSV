@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo CSV Import Studio v5 Space Edition - Demo Launcher
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import tkinter" >nul 2>&1
  if not errorlevel 1 (
    py -3 app.py --demo
    if not errorlevel 1 exit /b 0
    goto :failed
  )
)
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import tkinter" >nul 2>&1
  if not errorlevel 1 (
    python app.py --demo
    if not errorlevel 1 exit /b 0
    goto :failed
  )
)
echo.
echo ERROR: Python or tkinter is not installed correctly.
echo Install Python 3.10+ including tcl/tk and IDLE from python.org.
echo You can try: py -3 -m tkinter
echo.
pause
exit /b 1
:failed
echo.
echo ERROR: The app failed to start. Copy the error above and share it for troubleshooting.
pause
exit /b 1
