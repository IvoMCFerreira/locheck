@echo off
REM Double-click this, or drag one or two .plist files onto it.
REM
REM It exists because the people who most need this check are not always the
REM people with a terminal open. Double-clicking runs it against the two newest
REM localisation files sitting next to it; dragging files on runs it against
REM those. The window stays open at the end so the report can be read.
REM
REM Deliberately no `mode con` resize. An earlier version forced 120 columns to
REM stop issue titles wrapping, but `mode con` sets the screen *buffer*, and a
REM buffer pinned at 120 cannot grow - maximising the window left the report
REM boxed into the left 120 columns with dead space beside it. The tool measures
REM the terminal on every render instead, so it fills whatever window it is given.
REM
REM The interpreter is chosen by asking which one can import the tool, rather
REM than by assuming. An earlier version called `py -3` first and hid its errors:
REM on a machine with two Pythons that meant the check never ran, and the
REM non-zero exit was reported to the reader as "blockers found". A launcher that
REM invents a verdict is worse than no launcher, so nothing below claims a result
REM unless the tool actually produced one.

setlocal
cd /d "%~dp0"

python -c "import locheck, rich" >nul 2>&1
if errorlevel 1 goto try_launcher
set "PY=python"
goto run

:try_launcher
py -3 -c "import locheck, rich" >nul 2>&1
if errorlevel 1 goto first_run
set "PY=py -3"
goto run

REM ---------------------------------------------------------------------------
REM Nothing is set up yet. Offering to do it here rather than printing a pip
REM command is the whole point: telling someone without a terminal to open a
REM terminal is telling them to give up.
REM ---------------------------------------------------------------------------
:first_run
python --version >nul 2>&1
if errorlevel 1 goto try_launcher_for_setup
set "SETUP=python"
goto offer

:try_launcher_for_setup
py -3 --version >nul 2>&1
if errorlevel 1 goto no_python
set "SETUP=py -3"
goto offer

:offer
echo.
echo   First run on this machine.
echo.
echo   This needs one Python package ^(rich^) to draw the report. It installs
echo   into your Python only, and takes a few seconds.
echo.
echo   Set it up now? [Y/N]
set "ANSWER="
set /p "ANSWER=> "
if /i not "%ANSWER%"=="Y" goto declined

echo.
echo   Installing...
echo.
%SETUP% -m pip install -e . --quiet
if errorlevel 1 goto setup_failed
set "PY=%SETUP%"
echo   Done.
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

:declined
echo.
echo   Nothing installed. Run this again when you are ready, or from a
echo   terminal in this folder:  pip install -e .
set "CODE=3"
goto end

:setup_failed
echo.
echo   The install did not finish. The usual cause is no internet connection,
echo   or a Python installed without pip.
echo.
echo   From a terminal in this folder, this shows the actual error:
echo       %SETUP% -m pip install -e .
set "CODE=3"
goto end

:no_python
echo.
echo   No Python found on this machine.
echo.
echo   Install it from https://python.org/downloads - tick "Add Python to PATH"
echo   during setup - then double-click this file again.
set "CODE=3"
goto end

:end
echo.
pause
exit /b %CODE%
