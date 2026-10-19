@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
title 心晴 - 一键启动（后端模型 + 学生端 + 管理端）

REM ============================================================
REM   心晴 一键启动
REM   [1] 决策模型服务 Ollama        127.0.0.1:11434
REM   [2] 后端 FastAPI（视觉/语音模型）127.0.0.1:8000
REM   [3] 学生端网页                 127.0.0.1:5174
REM   [4] 管理端网页                 127.0.0.1:5173
REM   等各端口就绪后，自动打开学生端 + 管理端网页
REM ============================================================

set "ROOT=%~dp0"
REM ---- 定位 Python 解释器：优先环境变量 AIC_PYTHON，其次常见 conda 路径，最后 PATH 中的 python ----
set "PY=%AIC_PYTHON%"
if not defined PY if exist "%USERPROFILE%\anaconda3\envs\mental-health-agent\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\mental-health-agent\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\envs\mental-health-agent\python.exe" set "PY=%USERPROFILE%\miniconda3\envs\mental-health-agent\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\anaconda3\envs\mental-health-agent\python.exe" set "PY=%LOCALAPPDATA%\anaconda3\envs\mental-health-agent\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\miniconda3\envs\mental-health-agent\python.exe" set "PY=%LOCALAPPDATA%\miniconda3\envs\mental-health-agent\python.exe"
if not defined PY if exist "%ROOT%.venv\Scripts\python.exe" set "PY=%ROOT%.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" if exist "%ProgramFiles%\Ollama\ollama.exe" set "OLLAMA=%ProgramFiles%\Ollama\ollama.exe"

echo ============================================================
echo   心晴 - 一键启动
echo ============================================================
echo.

if not exist "%PY%" (
  echo [错误] 找不到 Python 解释器：
  echo        %PY%
  echo        请设置环境变量 AIC_PYTHON 指向 conda 环境的 python.exe，或把它加入系统 PATH
  echo.
  pause
  exit /b 1
)

REM ---------- [1/4] Ollama 决策模型服务 ----------
netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  if exist "%OLLAMA%" (
    echo [1/4] 启动 Ollama 决策模型服务（127.0.0.1:11434）...
    start "心晴-Ollama-11434" cmd /k "%OLLAMA%" serve
  ) else (
    echo [1/4] [警告] 未找到 Ollama：%OLLAMA%
  )
) else (
  echo [1/4] Ollama 已在运行，跳过。
)

REM ---------- [2/4] 后端 FastAPI ----------
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  echo [2/4] 启动后端 FastAPI（127.0.0.1:8000，首次加载模型约 30~90 秒）...
  start "心晴-后端-8000" /D "%ROOT%" cmd /k "%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
) else (
  echo [2/4] 端口 8000 已在监听，跳过启动后端。
)

REM ---------- [3/4] 学生端 ----------
netstat -ano | findstr ":5174 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  echo [3/4] 启动学生端（http://127.0.0.1:5174）...
  start "心晴-学生端-5174" /D "%ROOT%frontend-vue\student" cmd /k npm run dev
) else (
  echo [3/4] 端口 5174 已在监听，跳过启动学生端。
)

REM ---------- [4/4] 管理端 ----------
netstat -ano | findstr ":5173 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  echo [4/4] 启动管理端（http://127.0.0.1:5173）...
  start "心晴-管理端-5173" /D "%ROOT%frontend-vue\admin" cmd /k npm run dev
) else (
  echo [4/4] 端口 5173 已在监听，跳过启动管理端。
)

REM ---------- 等各端口就绪（关键：避免页面打开过早报“拒绝连接”） ----------
echo.
echo 等待服务就绪（后端首次加载模型较慢，请稍候，会打印进度点）...
call :waitport 8000 150
call :waitport 5174 60
call :waitport 5173 60

netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [警告] Ollama（11434）未就绪，决策模型可能不可用，请查看 Ollama 窗口的报错。
)

echo.
echo 正在打开页面 ...
start "" "http://127.0.0.1:5174/"
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:5173/"

echo.
echo ============================================================
echo   启动完成
echo ------------------------------------------------------------
echo   学生端：  http://127.0.0.1:5174/
echo   管理端：  http://127.0.0.1:5173/
echo   后端文档：http://127.0.0.1:8000/docs
echo ------------------------------------------------------------
echo   每个服务在独立窗口运行，关闭对应窗口即停止该服务。
echo   关闭本窗口不会停止已启动的服务。
echo ============================================================
echo.
pause
exit /b 0

REM ========== 子过程：等待指定端口进入 LISTENING 状态 ==========
:waitport
set "P=%~1"
set "LIM=%~2"
set /a m=0
:wp
set /a m+=1
netstat -ano | findstr ":%P% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo   - 端口 %P% 已就绪
  exit /b 0
)
if !m! GEQ %LIM% (
  echo.
  echo   [警告] 端口 %P% 等待超时，请检查对应窗口的报错信息。
  exit /b 1
)
<nul set /p "=."
timeout /t 1 /nobreak >nul
goto wp
