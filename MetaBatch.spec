# -*- mode: python ; coding: utf-8 -*-
"""MetaBatch 打包配置（PyInstaller）。

要点：
  - 输出名 MetaBatch，窗口模式，携带程序图标；
  - 完整收集 playwright（含自带 node 驱动），打包 assets 资源；
  - 启用两个运行时钩子：崩溃兜底 + Qt/ICU DLL 搜索路径；
  - 裁剪未使用的 Qt 模块，以及环境中被第三方库 try/except 误收集、
    项目实际不依赖的可选包（numpy/lxml/h2/cryptography 等）；
  - optimize=2 移除断言/文档字符串；
  - upx=False：项目实测 UPX 会压坏 Qt/ICU DLL，导致 QtCore 加载失败。

注意：Chromium 浏览器本体位于用户目录 ms-playwright 缓存，不在 pip 包内，
不会被收集；分发到未安装浏览器的机器时需先执行 `playwright install chromium`。
"""

import os

from PyInstaller.utils.hooks import collect_all

# Playwright：完整收集 Python 模块、自带 node 驱动（binaries）与数据文件。
pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")

# 项目运行时只使用 QtCore / QtGui / QtWidgets。
# 保留 QtNetwork / QtOpenGL / QtSvg / QtPrintSupport（常被基础 GUI 隐式依赖），
# 其余重型/专用 Qt 模块一律裁剪。
qt_excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDataVisualization",
    "PySide6.QtCharts",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtLocation",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtHelp",
    "PySide6.QtDesigner",
    "PySide6.QtXml",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtConcurrent",
]

# 环境中安装、但项目代码完全不引用的可选依赖。
# 已实测：requests 的 https 走标准库 ssl（OpenSSL 1.1）、openpyxl 走标准库
# xml、urllib3 默认 HTTP/1.1，因此这些包缺失不影响功能。
extra_excludes = [
    "numpy",            # 含 numpy.libs 的 OpenBLAS（DLL 另在下方过滤）
    "lxml",             # openpyxl 可选，回退标准库 xml
    "yaml",             # PyYAML，未使用
    "h2", "hpack", "hyperframe",   # urllib3 可选 HTTP/2，默认 HTTP/1.1
    "cryptography",     # requests/urllib3 走标准库 ssl
    "bcrypt",           # 未使用
    "PIL._avif", "PIL.AvifImagePlugin",   # 不读写 AVIF
]

excludes = qt_excludes + extra_excludes

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=pw_binaries,
    datas=[("assets", "assets")] + pw_datas,
    hiddenimports=pw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        "runtime_hooks/crash_handler.py",  # 必须最先：全局崩溃兜底
        "runtime_hooks/qt_dll_path.py",    # 注册 Qt / ICU DLL 搜索路径
    ],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)


# 二进制（DLL）级二次过滤。
def _drop_binary(dest):
    name = os.path.basename(dest).lower()
    normalized = dest.replace("\\", "/").lower()
    # Python 绑定已排除，剔除残留的 Qml/Quick/Pdf/VirtualKeyboard Qt DLL
    if name.startswith(("qt6qml", "qt6quick", "qt6pdf", "qt6virtualkeyboard")):
        return True
    # 纯软件 OpenGL 回退（本程序为传统 Widgets，走 d3d，不需要）
    if name == "opengl32sw.dll":
        return True
    # numpy 的 OpenBLAS
    if "numpy.libs" in normalized:
        return True
    # Python 3.11 标准库 ssl 使用 OpenSSL 1.1，剔除多余的 OpenSSL 3
    if name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
        return True
    return False


a.binaries = [entry for entry in a.binaries if not _drop_binary(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MetaBatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 项目经验：UPX 会压坏 Qt/ICU DLL，导致 QtCore 加载失败
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/metabatch_icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MetaBatch",
)
