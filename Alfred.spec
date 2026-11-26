# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/vosk-model-small-en-us-0.15', 'assets/vosk-model-small-en-us-0.15'), ('creative', 'creative'), ('phone', 'phone'), ('ui', 'ui'), ('archmancer_docs', 'archmancer_docs'), ('cloud/worker.js', 'cloud'), ('packaging/nova.png', 'packaging')]
binaries = []
hiddenimports = ['win32api', 'pywintypes', 'pythoncom', 'win32com', 'win32com.client', 'sounddevice', 'soundcard', 'vosk', 'mss', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'pystray._win32', 'soundfile', '_soundfile']
# Packages that load native libraries, data files or parts of themselves at runtime, so all of each is bundled:
# winrt (OCR, media), vosk (its DLL), docx/pptx (Office templates), libzim (offline Wikipedia), anthropic (lazy
# SDK parts), mediapipe (graph resources), sherpa_onnx (Kokoro voice: onnxruntime), bleak (Bluetooth backend),
# playwright (its driver drives Edge for Nova's own browser).
for package in ('winrt', 'vosk', 'docx', 'pptx', 'libzim', 'anthropic', 'mediapipe', 'sherpa_onnx', 'bleak', 'playwright'):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas; binaries += package_binaries; hiddenimports += package_imports
soundfile_datas, soundfile_binaries, _ = collect_all('_soundfile_data')  # libsndfile for Telegram voice notes
datas += soundfile_datas; binaries += soundfile_binaries

a = Analysis(
    ['dashboard.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Nova',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='packaging/nova.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Nova',
)
