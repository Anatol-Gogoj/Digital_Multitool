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
REM       else ask. A PARENT folder resolves to its newest SLDEA_* run.
REM    4. Open the tuner on it.
REM
REM  Save in the tuner writes the tuned values into that run's setup.txt, so
REM  work on a LOCAL copy of the run, not on the share.
REM
REM  Every step prints what it is doing and every failure explains itself and
REM  waits, so nothing ever closes silently.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
title SLDEA edge tuner - launcher

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
if exist "%~dp0..\sldea_tuner.py" set "APP=%~dp0.."
REM the share: this file sits in _software\ next to the SCPI_Control folder
if not defined APP if exist "%~dp0SCPI_Control\sldea_tuner.py" set "APP=%~dp0SCPI_Control"
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
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    set "WHY=This Python was installed without tkinter, the graphical toolkit the tuner needs."
    set "HOW=Re-run the Python installer, choose Modify, and enable 'tcl/tk and IDLE'. Then run this launcher again."
    goto :fail
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
"%VENV%\Scripts\python.exe" -c "import numpy, cv2, matplotlib, tkinter" >nul 2>&1
if errorlevel 1 (
    echo       Installing packages - needs internet, please wait...
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >>"%LOG%" 2>&1
    "%VENV%\Scripts\python.exe" -m pip install numpy opencv-python-headless matplotlib >>"%LOG%" 2>&1
    "%VENV%\Scripts\python.exe" -c "import numpy, cv2, matplotlib, tkinter" >nul 2>&1
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
echo [4/5] Finding the run to tune...
set "TARGET=%~1"
if not defined TARGET if defined SCPI_SLDEA_DIR set "TARGET=%SCPI_SLDEA_DIR%"
if not defined TARGET (
    echo       No folder given and SCPI_SLDEA_DIR is not set - opening a picker.
    for /f "usebackq delims=" %%p in (`powershell -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Pick an SLDEA run folder (or the parent folder holding the runs)'; if($d.ShowDialog() -eq 'OK'){$d.SelectedPath}" 2^>nul`) do set "TARGET=%%p"
)
if not defined TARGET (
    set "WHY=No run folder was chosen."
    set "HOW=Drag a run folder onto this launcher, or set the folder that holds the runs once with:  setx SCPI_SLDEA_DIR ""C:\SLDEA""  and open a new window."
    goto :fail
)
if not exist "!TARGET!" (
    set "WHY=The folder !TARGET! does not exist."
    set "HOW=Copy the run folder to this PC first - tuning writes setup.txt into it, and reading frames over the network is slow - then drag the local copy onto this launcher."
    goto :fail
)
pushd "%APP%"
set "RUNDIR="
if exist "!TARGET!\data.csv" (
    set "RUNDIR=!TARGET!"
) else (
    REM a parent folder: reuse the tuner's own resolver so this launcher and
    REM the app's Tune buttons always agree on what "newest run" means
    for /f "usebackq delims=" %%r in (`"%VENV%\Scripts\python.exe" -c "import sys, sldea_tuner as t; print(t._newest_run(sys.argv[1]) or '')" "!TARGET!" 2^>nul`) do set "RUNDIR=%%r"
)
if not defined RUNDIR (
    popd
    set "WHY=No SLDEA run was found in !TARGET!."
    set "HOW=A run folder holds data.csv and a frames folder. If you pointed at the folder that CONTAINS the runs, note that auto-discovery only sees sub-folders named SLDEA_* that contain a data.csv - otherwise drag the run folder itself onto this launcher."
    goto :fail
)
echo       OK - !RUNDIR!
echo.

REM ---- 5/5 launch ------------------------------------------------------
echo [5/5] Starting the tuner...
echo.
echo       Keep this window open while the tuner runs.
echo       Save writes the tuned values into the run's setup.txt, which
echo       Edge Review and auto-process then use.
echo.
"%VENV%\Scripts\python.exe" "%APP%\sldea_tuner.py" "!RUNDIR!"
set "RC=!ERRORLEVEL!"
popd
if not "!RC!"=="0" (
    set "WHY=The tuner stopped with error code !RC!. The lines printed above are the actual error."
    set "HOW=Copy the text above and send it to the maintainer. If it mentions a missing module, delete the folder %TUNEVENV% and run this launcher again to rebuild the environment."
    goto :fail
)
echo.
echo  Tuner closed normally.
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
