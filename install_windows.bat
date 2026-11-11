@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Installing PyMySQL for CSV Import Studio v5 Space Edition ...
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m pip install -r requirements.txt
  if not errorlevel 1 goto :success
  goto :failed
)
where python >nul 2>&1
if not errorlevel 1 (
  python -m pip install -r requirements.txt
  if not errorlevel 1 goto :success
  goto :failed
)
echo ERROR: Python is not installed. Install Python 3.10+ first.
goto :failed
:success
echo.
echo Installation finished. You may now run open_app.pyw.
pause
exit /b 0
:failed
echo.
echo Installation failed. Check the error above, your Python version, and Internet access.
pause
exit /b 1
