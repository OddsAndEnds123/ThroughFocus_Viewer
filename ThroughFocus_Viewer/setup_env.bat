@echo off
rem ThroughFocus_Viewer env setup (Windows)
rem Env lives at %%USERPROFILE%%\.conda\ThroughFocusViewer (short path).
rem Project tree under Documents\... is too long for PySide6 on default MAX_PATH.
rem No Python? Use ..\Release\ThroughFocus_Viewer_Win64\ThroughFocus_Viewer.exe
rem Usage: setup_env.bat
setlocal EnableExtensions
cd /d "%~dp0"
set "TF_RC=0"
set "TF_ENV=%USERPROFILE%\.conda\ThroughFocusViewer"
set "TF_VPY=%TF_ENV%\Scripts\python.exe"

where py >nul 2>&1
if not errorlevel 1 goto use_py_launcher
where python >nul 2>&1
if not errorlevel 1 goto use_python
goto no_python

:use_py_launcher
echo [1/4] Creating env ThroughFocusViewer with py -3 ...
if not exist "%USERPROFILE%\.conda" mkdir "%USERPROFILE%\.conda"
py -3 -m venv "%TF_ENV%"
if errorlevel 1 goto fail_venv
goto venv_ready

:use_python
echo [1/4] Creating env ThroughFocusViewer with python ...
if not exist "%USERPROFILE%\.conda" mkdir "%USERPROFILE%\.conda"
python -m venv "%TF_ENV%"
if errorlevel 1 goto fail_venv
goto venv_ready

:fail_venv
echo [ERROR] Failed to create %TF_ENV%
echo Python on PATH may be missing, broken, or only a Windows Store stub.
echo.
echo If this PC has no Python, do NOT use setup_env.bat.
echo Use the standalone package instead:
echo   ..\Release\ThroughFocus_Viewer_Win64\ThroughFocus_Viewer.exe
set "TF_RC=1"
goto finish

:no_python
echo [ERROR] Python not found on PATH.
echo Option A — install Python 3.12 x64, then re-run setup_env.bat
echo Option B — no Python: ..\Release\ThroughFocus_Viewer_Win64\ThroughFocus_Viewer.exe
set "TF_RC=1"
goto finish

:venv_ready
if exist "%TF_VPY%" goto have_vpy
echo [ERROR] %TF_VPY% missing
set "TF_RC=1"
goto finish

:have_vpy
echo [2/4] Upgrading pip ...
"%TF_VPY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] pip upgrade failed
  set "TF_RC=1"
  goto finish
)

echo [3/4] Installing requirements.txt ...
"%TF_VPY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo [ERROR] pip install failed
  set "TF_RC=1"
  goto finish
)

echo [4/4] Smoke import check ...
set "PYTHONPATH=%~dp0src"
"%TF_VPY%" "%~dp0tools\smoke_import.py"
if errorlevel 1 (
  echo [ERROR] Smoke import failed
  set "TF_RC=1"
  goto finish
)

echo.
echo [OK] Environment ThroughFocusViewer ready.
echo Path: %TF_ENV%
echo Run: run_throughfocus_viewer.bat
echo Python: %TF_VPY%

:finish
if not "%TF_RC%"=="0" pause
exit /b %TF_RC%
