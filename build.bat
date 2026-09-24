@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================
echo            MetaBatch 一键打包
echo   使用 main.spec 配置（窗口模式 / 已裁剪 / 关 UPX）
echo ==============================================
echo.

py -3.11 -m PyInstaller --clean --noconfirm MetaBatch.spec

echo.
if errorlevel 1 (
    echo [失败] 打包过程出现错误，请查看上方日志。
) else (
    echo [完成] 产物路径：
    echo        %cd%\dist\MetaBatch\MetaBatch.exe
)
echo.
pause
