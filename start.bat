@echo off
chcp 65001 >nul 2>&1
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM  文件轉檔 v2.0 — 桌面應用啟動器
REM  File Converter v2.0 — Desktop Launcher
REM  本腳本啟動 PySide6 桌面應用，僅依賴本機 venv 的 Python
REM  This launcher uses ONLY the local venv Python, no system PATH dependency
REM ============================================================

echo ============================================================
echo   文件轉檔 v2.0 / File Converter v2.0
echo   本機運行 . 永久免費 . 無限制
echo   Local . Free . Unlimited
echo ============================================================
echo.

REM ------------------------------------------------------------
REM  Step 1: Check virtual environment (the only required Python)
REM  Step 1: 檢查虛擬環境（唯一需要的 Python，不依賴系統 PATH）
REM ------------------------------------------------------------
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at: %~dp0venv\Scripts\python.exe
    echo [錯誤] 找不到虛擬環境 venv
    echo.
    echo   To set up the environment, please run these commands:
    echo   請執行下列指令建立環境（需先安裝 Python 3.10+）：
    echo.
    echo     python -m venv venv
    echo     venv\Scripts\pip install -r requirements.txt
    echo.
    echo   Download Python / Python 下載:
    echo     https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM [1/2] venv ready
echo [1/2] Virtual environment ready / 虛擬環境就緒

REM ------------------------------------------------------------
REM  Step 2: Launch desktop application (foreground)
REM  Step 2: 啟動桌面應用（前景執行，關閉此視窗即停止應用）
REM ------------------------------------------------------------
echo [2/2] Launching desktop application... / 啟動桌面應用...
echo.

"%~dp0venv\Scripts\python.exe" -m desktop
set APP_EXIT_CODE=%ERRORLEVEL%

REM ------------------------------------------------------------
REM  Handle abnormal exit / 處理非正常退出
REM ------------------------------------------------------------
if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo ============================================================
    echo   [WARNING] Application exited abnormally / 桌面應用非正常退出
    echo   Exit code / 退出代碼: %APP_EXIT_CODE%
    echo.
    echo   Possible causes / 可能原因:
    echo     1. Missing dependencies / 缺少套件:
    echo        venv\Scripts\pip install -r requirements.txt
    echo     2. Display driver issue / 顯示驅動問題
    echo        Update your GPU driver / 更新顯示卡驅動
    echo     3. Check error messages above / 查看上方錯誤訊息
    echo ============================================================
    echo.
    pause
    exit /b %APP_EXIT_CODE%
)

endlocal
exit /b 0
