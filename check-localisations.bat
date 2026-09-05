@echo off
REM Double-click this, or drag one or two .plist files onto it.
REM
REM It exists because the people who most need this check are not always the
REM people with a terminal open. Double-clicking runs it against the two newest
REM localisation files sitting next to it; dragging files on runs it against
REM those. The window stays open at the end so the report can actually be read.
REM
REM The interpreter is chosen by asking which one can import the tool, rather
REM than by assuming. An earlier version called `py -3` first and hid its
REM errors: on a machine with two Pythons that meant the check never ran, and
REM the non-zero exit was reported to the reader as "blockers found". A launcher
REM that invents a verdict is worse than no launcher, so nothing below claims a
REM result unless the tool actually produced one.

setlocal
cd /d "%~dp0"

python -c "import locheck, rich" >nul 2>&1
if errorlevel 1 goto try_launcher
set "PY=python"
goto run

:try_launcher
py -3 -c "import locheck, rich" >nul 2>&1
if errorlevel 1 goto not_installed
set "PY=py -3"
goto run

:run
echo.
%PY% -m locheck %*
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
    echo   Nothing blocking. Safe to ship.
) else if "%CODE%"=="1" (
    echo   Blockers found - see above. Do not ship yet.
) else if "%CODE%"=="2" (
    echo   Could not read the files - see the message above.
) else (
    echo   The check did not finish properly ^(exit code %CODE%^).
    echo   Nothing above should be treated as a verdict.
)
goto end

:not_installed
echo.
echo   Could not find a Python with this tool available.
echo.
echo   To set it up once: open a terminal in this folder and run
echo       pip install -e .
echo.
echo   Then double-click this file again.
set "CODE=3"

:end
echo.
pause
exit /b %CODE%
