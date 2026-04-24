# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 文件轉檔工具

使用方式：
  1. pip install pyinstaller
  2. pyinstaller build.spec
  3. 產物位於 dist/文件轉檔/

注意：
  - 打包為 onedir（不是 onefile），因轉檔引擎動態載入資源
  - 產物約 300-500MB（含所有 Python 依賴）
  - 仍需 MS Word（若要 DOCX→PDF）或 GTK runtime（若要輸出 PDF）
  - icon 需要 favicon.ico 存在於 static/ 目錄
"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('config.py', '.'),
    ],
    hiddenimports=[
        'pdf2docx',
        'fitz',
        'docx',
        'pptx',
        'docx2pdf',
        'weasyprint',
        'markdown',
        'bs4',
        'html2text',
        'PIL',
        'pythoncom',
        'win32com',
        'win32com.client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='文件轉檔工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon='static/favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='文件轉檔',
)
