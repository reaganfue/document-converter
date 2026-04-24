# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec 用於打包桌面版文件轉檔工具（onedir 模式）。

打包指令：
    venv/Scripts/python.exe -m PyInstaller desktop_build.spec --clean --noconfirm

產物位於：dist/文件轉檔/文件轉檔.exe
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 專案根（spec 檔所在位置）
ROOT = Path(SPECPATH)

# ─────────────────────────────────────────────
# 資料檔案：打包時複製至 dist/文件轉檔/
# ─────────────────────────────────────────────
datas = [
    # 桌面應用資源（圖示、QSS）
    (str(ROOT / 'desktop' / 'resources'), 'desktop/resources'),
]

# ─────────────────────────────────────────────
# Hidden imports — PyInstaller 靜態分析可能漏掉的模組
# ─────────────────────────────────────────────

# 收集 qfluentwidgets 所有子模組（資源全嵌入 _rc/resource.py，無需 datas）
_qfw_submodules = collect_submodules('qfluentwidgets')

hiddenimports = [
    # ── converters 套件（全部明確列出，確保 dispatcher 能動態路由） ──
    'converters',
    'converters.base',
    'converters.dispatcher',
    'converters.exceptions',
    'converters.utils',
    'converters.pdf_converter',
    'converters.pdf_renderer',
    'converters.word_converter',
    'converters.ppt_converter',
    'converters.html_converter',
    'converters.markdown_converter',
    'converters.txt_converter',
    'converters.image_converter',

    # ── desktop 套件 ──
    'desktop',
    'desktop.main',
    'desktop.main_window',
    'desktop.interfaces',
    'desktop.utils',
    'desktop.utils.theme',
    'desktop.utils.paths',
    'desktop.widgets',
    'desktop.widgets.drop_zone',
    'desktop.widgets.file_card',
    'desktop.widgets.format_selector',
    'desktop.widgets.progress_widget',
    'desktop.widgets.settings_dialog',
    'desktop.controllers',
    'desktop.controllers.conversion_controller',
    'desktop.controllers.job_manager',
    'desktop.controllers.settings_manager',
    'desktop.controllers.notification_manager',
    'desktop.controllers.history_manager',
    'desktop.controllers.tray_manager',

    # ── desktop pages（W-COMMERCIAL 5 分頁） ──
    'desktop.pages',
    'desktop.pages.base_page',
    'desktop.pages.home_page',
    'desktop.pages.batch_page',
    'desktop.pages.history_page',
    'desktop.pages.settings_page',
    'desktop.pages.about_page',
    'desktop.pages.components',
    'desktop.pages.components.stats_bar',

    # ── desktop database（SQLite 歷史記錄層） ──
    'desktop.database',
    'desktop.database.history_db',
    'desktop.database.migrations',

    # ── desktop main_window_v2（商用版主視窗） ──
    'desktop.main_window_v2',

    # ── desktop utils 補充 ──
    'desktop.utils.i18n',

    # ── PDF 相關 ──
    'fitz',
    'fitz.fitz',
    'pdf2docx',
    'reportlab',
    'reportlab.pdfgen',
    'reportlab.pdfgen.canvas',
    'reportlab.lib',
    'reportlab.lib.pagesizes',

    # ── Word / DOCX 相關 ──
    'docx',
    'docx.shared',
    'docx.oxml',
    'docx2pdf',
    'pythoncom',
    'win32com',
    'win32com.client',

    # ── PowerPoint 相關 ──
    'pptx',
    'pptx.util',

    # ── HTML 相關 ──
    'bs4',
    'bs4.builder',
    'bs4.builder._html5lib',
    'bs4.builder._htmlparser',
    'bs4.builder._lxml',
    'html2text',

    # ── Markdown 相關 ──
    'markdown',
    'markdown.extensions',
    'markdown.extensions.fenced_code',
    'markdown.extensions.tables',

    # ── 圖片相關 ──
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.BmpImagePlugin',
    'PIL.TiffImagePlugin',
    'PIL.WebPImagePlugin',

    # ── 主題 / 系統 ──
    'darkdetect',
    'winreg',

    # ── 標準庫補充（某些版本 PyInstaller 會漏） ──
    'concurrent.futures',
    'threading',
    'uuid',
    'dataclasses',
    'importlib',
    'importlib.util',
    'importlib.metadata',
    'sqlite3',
    'csv',
    'json',

    # ── qfluentwidgets 所有子模組 ──
] + _qfw_submodules

# ─────────────────────────────────────────────
# 排除（減小體積、不需要打包的開發/測試工具）
# ─────────────────────────────────────────────
excludes = [
    'tkinter', '_tkinter',
    'matplotlib', 'scipy', 'numpy.tests',
    'pytest', 'py', '_pytest',
    'notebook', 'IPython', 'ipykernel',
    'flask', 'jinja2', 'werkzeug',
    'sphinx', 'docutils',
]

# ─────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────
a = Analysis(
    [str(ROOT / 'desktop' / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─────────────────────────────────────────────
# EXE + COLLECT（onedir 模式）
# ─────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # onedir：DLL/資料由 COLLECT 管理
    name='文件轉檔',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,                # False = 不顯示黑色命令視窗（桌面應用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'desktop' / 'resources' / 'app.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='文件轉檔',
)
