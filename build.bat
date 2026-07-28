@echo off
:: 设置 CMD 为 UTF-8 编码，防止中文提示导致闪退
chcp 65001 >nul

echo --------------------------------------------------
echo   Watermark Studio Packaging Script
echo --------------------------------------------------
echo.

:: 1. 尝试生成图标 (app.ico)
if exist generate_icon.py (
    echo [1/3] Generating app.ico...
    python generate_icon.py
)

:: 2. 清理旧构建缓存
echo [2/3] Cleaning build caches...
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist *.spec del /f /q *.spec

:: 3. 检查 fonts 文件夹是否存在，准备打包参数
set ADD_DATA_PARAM=
if exist fonts (
    set ADD_DATA_PARAM=--add-data "fonts;fonts"
)

set ICON_PARAM=
if exist app.ico (
    set ICON_PARAM=--icon=app.ico
)

echo [3/3] Running PyInstaller...
pyinstaller --noconfirm --onedir --windowed %ICON_PARAM% %ADD_DATA_PARAM% main.py

echo.
echo --------------------------------------------------
if exist dist\main\main.exe (
    echo [SUCCESS] Package created: dist\main\main.exe
) else (
    echo [WARNING] Build finished. Please check the dist directory.
)
echo --------------------------------------------------
echo.
pause