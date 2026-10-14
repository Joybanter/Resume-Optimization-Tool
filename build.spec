# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（PRD 9.1 / 9.2）
#
# 使用方式（在 Windows 打包机执行）：
#   pip install pyinstaller
#   pyinstaller build.spec
# 输出：build/dist/ResumeOptimizer.exe（单文件、无控制台窗口）
#
# 注意：
# - docx2pdf 依赖 COM 调用 Word，打包产物仅 Windows 可用
# - 图标：放置 src/resources/icon.ico 后取消下方 icon 参数注释
# - 首次运行稍慢（单文件自解压），属正常现象

a = Analysis(
    ['src/main.py'],
    pathex=['.'],  # 项目根：使 src 作为包导入（入口用 from src.xxx import）
    binaries=[],
    datas=[
        ('src/resources', 'resources'),  # QSS 样式表等资源
        ('src/prompts', 'prompts'),      # Prompt 模板（模块化，便于后续扩展）
        ('src/easter egg', 'easter egg'),  # 彩蛋资源：rain.mp4 + 像素文字图
    ],
    hiddenimports=['docx2pdf'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 精简体积：排除开发期工具
        'pytest',
        'pyinstaller',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ResumeOptimizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                # 压缩以减小体积（PRD 9.1）
    console=False,           # 无控制台窗口（PRD 9.1）
    disable_windowed_traceback=False,
    # icon='src/resources/icon.ico',  # 放置图标后取消注释
)