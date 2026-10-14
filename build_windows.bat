@echo off
rem ============================================================
rem  简历优化工具 - Windows 一键打包脚本
rem
rem  前置要求：
rem    1. 已安装 Python 3.10+ 并加入 PATH（命令行 python 可用）
rem    2. 分发目标机器需安装 Microsoft Word 或 WPS（PDF 导出依赖）
rem
rem  使用：双击本文件，或在项目目录执行 build_windows.bat
rem  产物：dist\ResumeOptimizer.exe（单文件、无控制台窗口）
rem ============================================================
cd /d "%~dp0"

if not exist .venv-build (
    echo [1/3] 首次运行：创建打包虚拟环境并安装依赖（约 2-4 分钟）...
    python -m venv .venv-build
    call .venv-build\Scripts\activate.bat
    python -m pip install --upgrade pip -q
    pip install -r requirements.txt -q
) else (
    echo [1/3] 复用已有打包虚拟环境
    call .venv-build\Scripts\activate.bat
)

echo [2/3] PyInstaller 打包中（约 3-5 分钟，请勿关闭窗口）...
pyinstaller build.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [失败] 打包过程出错，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo        产物位置: %cd%\dist\ResumeOptimizer.exe
echo        分发方式: 将 ResumeOptimizer.exe 压缩为 zip 发给用户即可，
echo        双击运行无需安装 Python；首次启动稍慢（单文件自解压）属正常。
echo        注意：PDF 导出需目标机器安装 Word 或 WPS。
echo.
pause