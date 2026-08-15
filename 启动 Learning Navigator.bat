@echo off
setlocal
title Learning Navigator
cd /d "%~dp0"

set "LAUNCH_SCRIPT=%~dp0scripts\launch_learning_navigator.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%POWERSHELL_EXE%" set "POWERSHELL_EXE=powershell.exe"

if not exist "%LAUNCH_SCRIPT%" (
    echo.
    echo [ERROR] Launcher support file is missing:
    echo %LAUNCH_SCRIPT%
    goto :failed
)

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LAUNCH_SCRIPT%" %*
set "LAUNCH_EXIT_CODE=%ERRORLEVEL%"

if not "%LAUNCH_EXIT_CODE%"=="0" goto :failed_with_code

goto :pause

:failed_with_code
echo.
echo [ERROR] Learning Navigator could not start. Exit code: %LAUNCH_EXIT_CODE%
echo The detailed log path is shown above.
echo Launcher logs are stored under:
echo %~dp0launcher*.log
goto :pause

:failed
set "LAUNCH_EXIT_CODE=1"

:pause
echo.
echo Press any key to close this window...
pause >nul
exit /b %LAUNCH_EXIT_CODE%
