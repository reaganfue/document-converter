@echo off
chcp 65001 >nul 2>&1
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM  文件轉檔 v2.0 — 桌面應用啟動器（無 console 視窗版）
REM  File Converter v2.0 — Desktop Launcher (no-console)
REM
REM  使用 pythonw.exe + start "" 啟動 PySide6 桌面應用，
REM  cmd 視窗會立即關閉，工作列只剩應用本身，不再有黑色 console 視窗。
REM ============================================================

REM ------------------------------------------------------------
REM  Step 1: Check virtual environment (only required Python)
REM  Step 1: 檢查虛擬環境（必要時顯示錯誤；正常情況使用者不會看到此 cmd 視窗）
REM ------------------------------------------------------------
if not exist "%~dp0venv\Scripts\pythonw.exe" (
    echo ============================================================
    echo   [ERROR] Virtual environment not found / 找不到虛擬環境
    echo   Expected at: %~dp0venv\Scripts\pythonw.exe
    echo.
    echo   To set up the environment, please run / 請建立環境：
    echo.
    echo     python -m venv venv
    echo     venv\Scripts\pip install -r requirements.txt
    echo.
    echo   Download Python / Python 下載:
    echo     https://www.python.org/downloads/
    echo ============================================================
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM  Step 2: Launch desktop app as detached process (no console)
REM  Step 2: 以 detached 模式啟動桌面應用（無 console）
REM
REM  start ""    開啟新 process 不等待返回
REM  pythonw.exe Python interpreter without console window
REM ------------------------------------------------------------
start "" "%~dp0venv\Scripts\pythonw.exe" -m desktop

REM batch script 立即退出，cmd 視窗一閃即逝
endlocal
exit /b 0
