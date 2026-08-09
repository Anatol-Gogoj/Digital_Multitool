@echo off
REM ============================================================================
REM  SLDEA edge TUNER launcher for WINDOWS PCs -- double-click me, or drag a
REM  run folder onto me.
REM
REM  The tuner is a standalone Tk program that touches no instruments, so any
REM  Windows PC with a copy of the run data can tune. This launcher mirrors
REM  Launch_SCPI_Control_Windows.bat but stays small:
REM    1. Find the app (works from deploy/ in a checkout, from the share's
REM       _software folder, or against the launcher's local mirror).
REM    2. Reuse the main launcher's venv when it exists; otherwise build a
REM       tuner-only one -- numpy + opencv + matplotlib is all this needs.
REM    3. Resolve the run: the folder dropped on me, else %SCPI_SLDEA_DIR%,
REM       else ask. A PARENT folder resolves to the newest run inside it.
REM    4. Open the tuner on it -- or, with /diag, run the diagnostic.
REM
REM  Save in the tuner writes the tuned values into that run's setup.txt, so
REM  work on a LOCAL copy of the run, not on the share.
REM
REM  Every step prints what it is doing and every failure explains itself and
REM  waits, so nothing ever closes silently.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
title SLDEA edge tuner - launcher

REM  Pass /diag to run the run diagnostic (sldea_diag.py) instead of the
REM  tuner: it reports, in numbers, WHY a run will not tune -- drift,
REM  which map actually separates, threshold transfer, the gate. Make a
REM  shortcut with /diag in the target if you want it one click away.
REM  %~dp0 FIRST: `shift` below moves %0 as well as the arguments, so after
REM  parsing, %~dp0 no longer points at this file and every path built from
REM  it silently misses (bench 2026-07-28: "could not find sldea_tuner.py"
REM  from inside the checkout that contained it).
set "HERE=%~dp0"
set "MODE=tune"
set "TARGET="
:parseargs
if "%~1"=="" goto :parsed
if /i "%~1"=="/diag" (
    set "MODE=diag"
) else if /i "%~1"=="--diag" (
    set "MODE=diag"
) else if not defined TARGET (
    set "TARGET=%~1"
)
shift
goto :parseargs
:parsed

set "CACHE=%LOCALAPPDATA%\SCPI_Control"
set "APPVENV=%CACHE%\venv"
set "TUNEVENV=%CACHE%\venv-tuner"
set "LOG=%CACHE%\tuner-setup.log"
set "WHY="
set "HOW="

echo ==============================================================
echo    SLDEA edge tuner  --  Windows launcher
echo ==============================================================
echo.

if not exist "%CACHE%" mkdir "%CACHE%" >nul 2>&1

REM ---- 1/5 the app -----------------------------------------------------
echo [1/5] Locating the application...
set "APP="
REM a checkout: this file sits in deploy\, the app is its parent
if exist "%HERE%..\sldea_tuner.py" set "APP=%HERE%.."
REM the share: this file sits in _software\ next to the SCPI_Control folder
if not defined APP if exist "%HERE%SCPI_Control\sldea_tuner.py" set "APP=%HERE%SCPI_Control"
REM last resort: the local mirror the main launcher keeps up to date
if not defined APP if exist "%CACHE%\app\sldea_tuner.py" set "APP=%CACHE%\app"
if not defined APP (
    set "WHY=Could not find sldea_tuner.py next to this launcher."
    set "HOW=Keep this file inside the checkout's deploy folder, or on the ShareDrive next to the SCPI_Control folder. Alternatively run Launch_SCPI_Control_Windows.bat once - that mirrors the app to %CACHE%\app, which this launcher also accepts."
    goto :fail
)
for %%i in ("%APP%") do set "APP=%%~fi"
echo       OK - %APP%
echo.

REM ---- 2/5 python ------------------------------------------------------
echo [2/5] Looking for Python 3...
set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    set "WHY=No working Python 3 was found on this PC."
    set "HOW=Install Python 3.10 or newer from https://www.python.org/downloads/ - TICK 'Add python.exe to PATH' and keep the 'tcl/tk and IDLE' option enabled - then double-click this launcher again."
    goto :fail
)
%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    set "WHY=The Python installed on this PC is older than 3.10."
    set "HOW=Install a current Python from https://www.python.org/downloads/ - tick 'Add python.exe to PATH' - then run this launcher again."
    goto :fail
)
REM the diagnostic never opens a window, so do not fail it over tkinter
set "NEEDMODS=numpy, cv2, matplotlib"
if not "!MODE!"=="diag" (
    set "NEEDMODS=numpy, cv2, matplotlib, tkinter"
    %PY% -c "import tkinter" >nul 2>&1
    if errorlevel 1 (
        set "WHY=This Python was installed without tkinter, the graphical toolkit the tuner needs."
        set "HOW=Re-run the Python installer, choose Modify, and enable 'tcl/tk and IDLE'. Then run this launcher again. To run only the diagnostic, which needs no window, pass /diag."
        goto :fail
    )
)
echo       OK.
echo.

REM ---- 3/5 environment -------------------------------------------------
echo [3/5] Checking the Python environment...
REM prefer the main launcher's venv - it already carries the requirements
set "VENV=%TUNEVENV%"
if exist "%APPVENV%\Scripts\python.exe" set "VENV=%APPVENV%"
if not exist "%VENV%\Scripts\python.exe" (
    echo       First run on this PC - creating the tuner environment.
    %PY% -m venv "%VENV%" >>"%LOG%" 2>&1
    if errorlevel 1 (
        set "WHY=Could not create the Python environment in %VENV%."
        set "HOW=Make sure Python 3.10 or newer is properly installed, then delete the folder %VENV% and run this launcher again. Details are in %LOG%."
        goto :fail
    )
)
REM self-healing: install only when something is actually missing, so the
REM normal start stays offline and instant
"%VENV%\Scripts\python.exe" -c "import !NEEDMODS!" >nul 2>&1
if errorlevel 1 (
    echo       Installing packages - needs internet, please wait...
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >>"%LOG%" 2>&1
    "%VENV%\Scripts\python.exe" -m pip install numpy opencv-python-headless matplotlib >>"%LOG%" 2>&1
    "%VENV%\Scripts\python.exe" -c "import !NEEDMODS!" >nul 2>&1
    if errorlevel 1 (
        set "WHY=The tuner's Python packages could not be installed."
        set "HOW=Usually this means no internet connection. Connect and retry; if it still fails, delete the folder %TUNEVENV% and run this launcher again. The last lines of %LOG% say which package failed."
        goto :fail
    )
    echo       OK - packages installed.
) else (
    echo       OK - packages already present.
)
echo.

REM ---- 4/5 the run -----------------------------------------------------
echo [4/5] Finding the run to work on...
REM A SET-BUT-DANGLING SCPI_SLDEA_DIR used to dead-end the launcher: the
REM value was taken unconditionally, the picker below only fires when TARGET
REM is undefined, and the run then died at :fail with a confusing message.
REM Live example (analysis VM, 2026-08-09): the variable pointed at a
REM VirtualBox share that was no longer attached. Both Python front ends
REM already degrade -- sldea_edge.py swallows the OSError, sldea_tuner.py
REM opens its picker with a printed reason -- so this was the last place
REM that did not.
REM
REM The trailing-backslash test is deliberate and was MEASURED, not guessed:
REM `if exist "<path>\."` returns TRUE for a plain FILE, which would let a
REM file through as though it were a run folder. `"<path>\"` is false for a
REM dangling path AND for a file, and true only for a real directory.
if not defined TARGET if defined SCPI_SLDEA_DIR (
    if exist "%SCPI_SLDEA_DIR%\" (
        set "TARGET=%SCPI_SLDEA_DIR%"
    ) else (
        echo       SCPI_SLDEA_DIR is set, but is not a folder that exists:
        echo         %SCPI_SLDEA_DIR%
        echo       Ignoring it and opening a picker. Point it somewhere real with:
        echo         setx SCPI_SLDEA_DIR "C:\path\to\the\runs"
    )
)
if not defined TARGET (
    echo       No usable folder from SCPI_SLDEA_DIR - opening a picker.
    for /f "usebackq delims=" %%p in (`powershell -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Pick an SLDEA run folder (or the parent folder holding the runs)'; if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}" 2^>nul`) do set "TARGET=%%p"
)
if not defined TARGET (
    set "WHY=No run folder was chosen."
    set "HOW=Drag a run folder onto this launcher, or set the folder that holds the runs once with:  setx SCPI_SLDEA_DIR ""C:\SLDEA""  and open a new window."
    goto :fail
)
pushd "%APP%"
REM Resolve through the app itself: it accepts a run folder, a parent full
REM of runs, or a bench shortcut like 1/2/3. Done with a --resolve flag and
REM a temp file rather than `python -c "..."` inside a for /f -- cmd strips
REM the outer quotes of a command that STARTS with a quoted path and also
REM carries quoted arguments, which silently broke every path containing a
REM space (bench 2026-07-28). stderr goes to the log, never to nul: that
REM redirect is what made the failure invisible.
set "RESOLVED=%TEMP%\sldea_resolved.txt"
del "%RESOLVED%" >nul 2>&1
"%VENV%\Scripts\python.exe" "%APP%\sldea_tuner.py" --resolve "!TARGET!" >"%RESOLVED%" 2>>"%LOG%"
set "RUNDIR="
if exist "%RESOLVED%" set /p RUNDIR=<"%RESOLVED%"
del "%RESOLVED%" >nul 2>&1
if not defined RUNDIR (
    popd
    set "WHY=No SLDEA run was found for !TARGET!."
    set "HOW=A run folder holds a frames folder and data.csv - or data1.csv, data2.csv and so on if you renamed it. You can also pass the folder that CONTAINS the runs (the newest one inside it is used), or a bench shortcut: 1, 2 or 3. If this looks right, the end of %LOG% has the actual error."
    goto :fail
)
echo       OK - !RUNDIR!
echo.

REM ---- 5/5 launch ------------------------------------------------------
if "!MODE!"=="diag" (
    echo [5/5] Running the run diagnostic...
    echo.
    echo       It writes sldea_diag.txt / .json / .png into the run folder.
    echo       The .json is data only - small enough to send on.
    echo.
    "%VENV%\Scripts\python.exe" "%APP%\sldea_diag.py" "!RUNDIR!"
) else (
    echo [5/5] Starting the tuner...
    echo.
    echo       Keep this window open while the tuner runs.
    echo       Save writes the tuned values into the run's setup.txt, which
    echo       Edge Review and auto-process then use.
    echo.
    "%VENV%\Scripts\python.exe" "%APP%\sldea_tuner.py" "!RUNDIR!"
)
set "RC=!ERRORLEVEL!"
popd
if not "!RC!"=="0" (
    set "WHY=It stopped with error code !RC!. The lines printed above are the actual error."
    set "HOW=Copy the text above and send it to the maintainer. If it mentions a missing module, delete the folder %TUNEVENV% and run this launcher again to rebuild the environment."
    goto :fail
)
echo.
echo  Closed normally.
timeout /t 3 >nul
endlocal
exit /b 0

REM ---- failure handler --------------------------------------------------
:fail
echo.
echo --------------------------------------------------------------
echo   PROBLEM
echo     !WHY!
echo.
echo   WHAT TO DO
echo     !HOW!
echo --------------------------------------------------------------
if exist "%LOG%" (
    echo.
    echo   Last lines of the setup log - full log: %LOG%
    echo.
    powershell -NoProfile -Command "Get-Content -Tail 20 -Path '%LOG%'" 2>nul
)
echo.
pause
endlocal
exit /b 1
