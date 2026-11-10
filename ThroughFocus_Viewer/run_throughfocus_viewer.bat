@echo off
rem ThroughFocus_Viewer - through-focus ROI viewer
rem Usage: run_throughfocus_viewer.bat [image|folder|*.bmp ...]
rem Setup: setup_env.bat  (creates %%USERPROFILE%%\.conda\ThroughFocusViewer)
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "TF_RC=0"

if exist "%USERPROFILE%\.conda\ThroughFocusViewer\Scripts\python.exe" (
  set "TF_VPY=%USERPROFILE%\.conda\ThroughFocusViewer\Scripts\python.exe"
  goto do_run
)
if exist "%~dp0.conda\ThroughFocusViewer\Scripts\python.exe" (
  set "TF_VPY=%~dp0.conda\ThroughFocusViewer\Scripts\python.exe"
  goto do_run
)
if exist "%~dp0.venv\Scripts\python.exe" (
  set "TF_VPY=%~dp0.venv\Scripts\python.exe"
  goto do_run
)
where py >nul 2>&1
if not errorlevel 1 (
  goto do_run_py
)
where python >nul 2>&1
if not errorlevel 1 (
  set "TF_VPY=python"
  goto do_run
)
echo [ERROR] Env ThroughFocusViewer not found.
echo Run setup_env.bat first.
set "TF_RC=1"
goto end_run

:do_run_py
py -3 -m viewer %*
set "TF_RC=%ERRORLEVEL%"
goto end_run

:do_run
"%TF_VPY%" -m viewer %*
set "TF_RC=%ERRORLEVEL%"

:end_run
if not "%TF_RC%"=="0" pause
exit /b %TF_RC%
