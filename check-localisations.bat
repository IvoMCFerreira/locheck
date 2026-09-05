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

REM A console opened by double-clicking is 80 columns, which is narrower than
REM the report wants - issue titles wrap onto two lines and the detail cards get
REM cramped. 120 gives everything room.
REM
REM The second number is the screen *buffer*, not the window, so it is the
REM scrollback. It has to stay large: setting it to the window height would
REM leave the reader unable to scroll back to the blockers, which is the whole
REM point of the report. If the console refuses to resize, the tool adapts to
REM whatever width it finds, so the error is not worth showing.
mode con: cols=120 lines=9000 >nul 2>&1

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
