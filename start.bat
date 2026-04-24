@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  文件轉檔工具 v2.0  - 桌面應用啟動器
REM  說明：本腳本啟動 PySide6 桌面應用（文件轉檔 v2.0）
REM ============================================================

echo ============================================================
echo   文件轉檔 v2.0 -- 桌面應用啟動器
echo   本機運行  永久免費  無限制
echo ============================================================
echo.

REM ============================================================
REM  Step 1: 檢查 Python 是否已安裝並加入 PATH
REM ============================================================
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo [錯誤] 未偵測到 Python 3.10 以上版本
    echo.
    echo   請至下列網址下載並安裝 Python：
    echo   https://www.python.org/downloads/
    echo.
    echo   安裝時請務必勾選 "Add Python to PATH"
    echo   安裝完成後請重新雙擊 start.bat
    echo.
    pause
    exit /b 1
)

REM 取得並顯示 Python 版本
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [1/2] 已偵測到 %PYVER%

REM ============================================================
REM  Step 2: 確認虛擬環境已就緒
REM ============================================================
if not exist "%~dp0venv\Scripts\python.exe" (
    echo.
    echo [錯誤] 虛擬環境 venv/ 不存在或不完整
    echo.
    echo   請先執行下列指令建立環境：
    echo     python -m venv venv
    echo     venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo [2/2] 虛擬環境已就緒

echo.
echo ============================================================
echo   啟動文件轉檔桌面應用...
echo ============================================================
echo.

REM 啟動桌面應用（前景執行，關閉此視窗即停止應用）
"%~dp0venv\Scripts\python.exe" -m desktop
set APP_EXIT_CODE=%ERRORLEVEL%

REM 非正常退出時顯示提示
if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo ============================================================
    echo   [警告] 桌面應用非正常退出（代碼：%APP_EXIT_CODE%）
    echo.
    echo   可能原因：
    echo     1. 缺少 PySide6 套件 -- 請執行：
    echo        venv\Scripts\pip install -r requirements.txt
    echo     2. 顯示驅動不相容（請更新顯示驅動）
    echo     3. 查看上方錯誤訊息或 README.md 故障排除章節
    echo ============================================================
    echo.
    pause
    exit /b %APP_EXIT_CODE%
)

exit /b 0
