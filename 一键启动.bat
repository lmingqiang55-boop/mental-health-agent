@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title XinQing - one-click launcher

set "ROOT=%~dp0"
set "PY="

REM Prefer an explicitly configured Python, then the project-local environments.
if defined AIC_PYTHON if exist "%AIC_PYTHON%" set "PY=%AIC_PYTHON%"
if not defined PY if exist "%ROOT%.conda-env\python.exe" set "PY=%ROOT%.conda-env\python.exe"
if not defined PY if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\envs\mental-health-agent\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\mental-health-agent\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\envs\mental-health-agent\python.exe" set "PY=%USERPROFILE%\miniconda3\envs\mental-health-agent\python.exe"
REM Conda may be installed on another drive; use its registered environment paths.
if not defined PY if exist "%USERPROFILE%\.conda\environments.txt" (
  for /f "usebackq delims=" %%E in ("%USERPROFILE%\.conda\environments.txt") do (
    if not defined PY if /i "%%~nxE"=="mental-health-agent" if exist "%%E\python.exe" set "PY=%%E\python.exe"
  )
)

set "OLLAMA=%ROOT%..\tools\Ollama\ollama.exe"
if not exist "%OLLAMA%" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA=%ProgramFiles%\Ollama\ollama.exe"
if not defined OLLAMA_MODELS set "OLLAMA_MODELS=%ROOT%..\ollama-models"

echo ============================================================
echo   XinQing - one-click launcher
echo ============================================================
echo.

if not defined PY goto :python_missing
if not exist "%PY%" goto :python_missing

echo Python: %PY%

REM [1/4] Local policy model service.
call :is_listening 11434
if errorlevel 1 (
  if exist "%OLLAMA%" (
    echo [1/4] Starting Ollama on 127.0.0.1:11434 ...
    start "XinQing-Ollama-11434" /D "%ROOT%" "%ComSpec%" /k ""%OLLAMA%" serve"
  ) else (
    echo [1/4] WARNING: Ollama was not found.
  )
) else (
  echo [1/4] Ollama is already running.
)

REM [2/4] FastAPI backend. SenseVoice may need 30-120 seconds for its first load.
call :is_listening 8000
if errorlevel 1 (
  echo [2/4] Starting backend on 127.0.0.1:8000 ...
  start "XinQing-Backend-8000" /D "%ROOT%" "%ComSpec%" /k ""%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
) else (
  echo [2/4] Backend is already running.
)

REM [3/4] Student frontend.
call :is_listening 5174
if errorlevel 1 (
  echo [3/4] Starting student frontend on 127.0.0.1:5174 ...
  start "XinQing-Student-5174" /D "%ROOT%frontend-vue\student" "%ComSpec%" /k "npm run dev"
) else (
  echo [3/4] Student frontend is already running.
)

REM [4/4] Admin frontend.
call :is_listening 5173
if errorlevel 1 (
  echo [4/4] Starting admin frontend on 127.0.0.1:5173 ...
  start "XinQing-Admin-5173" /D "%ROOT%frontend-vue\admin" "%ComSpec%" /k "npm run dev"
) else (
  echo [4/4] Admin frontend is already running.
)

echo.
echo Waiting for the backend. The first ASR model load can be slow ...
call :wait_port 8000 180
if errorlevel 1 (
  echo.
  echo ERROR: backend did not open port 8000.
  echo Read the error shown in the XinQing-Backend-8000 window.
  echo.
  pause
  exit /b 1
)

call :wait_port 5174 60
call :wait_port 5173 60

start "" "http://127.0.0.1:5174/"
start "" "http://127.0.0.1:5173/"

echo.
echo ============================================================
echo   Ready
echo   Student: http://127.0.0.1:5174/
echo   Admin:   http://127.0.0.1:5173/
echo   API:     http://127.0.0.1:8000/docs
echo ============================================================
echo You may close this launcher window. Keep the service windows open.
pause
exit /b 0

:python_missing
echo ERROR: project Python was not found.
echo Expected: %ROOT%.conda-env\python.exe
echo You can also set AIC_PYTHON to the correct python.exe.
pause
exit /b 1

:is_listening
netstat -ano | findstr ":%~1 " | findstr "LISTENING" >nul 2>&1
exit /b %errorlevel%

:wait_port
set "PORT=%~1"
set "LIMIT=%~2"
set /a COUNT=0
:wait_loop
call :is_listening %PORT%
if not errorlevel 1 (
  echo   Port %PORT% is ready.
  exit /b 0
)
set /a COUNT+=1
if !COUNT! GEQ %LIMIT% exit /b 1
<nul set /p "=."
timeout /t 1 /nobreak >nul
goto :wait_loop
