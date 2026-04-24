@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================
echo   文件轉檔 -- PyInstaller 打包腳本
echo ============================================================
echo.

set VENV_PY=%~dp0venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [錯誤] 虛擬環境不存在：%VENV_PY%
    echo 請先執行：python -m venv venv
    echo 再執行：venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo [步驟 1/3] 清理舊的 build/ 和 dist/ 目錄...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"

echo [步驟 2/3] 執行 PyInstaller 打包...
"%VENV_PY%" -m PyInstaller desktop_build.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [錯誤] PyInstaller 打包失敗，請檢查以上輸出中的 ERROR 或 WARNING 訊息
    pause
    exit /b 1
)

echo [步驟 3/3] 驗證產物...
if not exist "%~dp0dist\文件轉檔\文件轉檔.exe" (
    echo [錯誤] 未生成 exe 檔案（dist\文件轉檔\文件轉檔.exe）
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   [完成] dist/文件轉檔/ 已產生
echo   可執行檔：dist\文件轉檔\文件轉檔.exe
echo   雙擊上述 exe 即可啟動桌面應用
echo ============================================================
pause
endlocal
exit /b 0
