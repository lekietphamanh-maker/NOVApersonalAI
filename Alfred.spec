# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/vosk-model-small-en-us-0.15', 'assets/vosk-model-small-en-us-0.15'), ('creative', 'creative'), ('phone', 'phone'), ('ui', 'ui'), ('cloud/worker.js', 'cloud'), ('packaging/nova.png', 'packaging')]
binaries = []
hiddenimports = ['win32api', 'win32ui', 'win32uiole', 'pywintypes', 'pythoncom', 'win32com', 'win32com.client', 'sounddevice', 'soundcard', 'vosk', 'mss', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageTk', 'pystray._win32']
tmp_ret = collect_all('winrt')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# Vosk's CFFI-based recognition needs its native DLL and dependent runtime DLLs
# alongside the Python package in the frozen onedir bundle.
vosk_ret = collect_all('vosk')
datas += vosk_ret[0]; binaries += vosk_ret[1]; hiddenimports += vosk_ret[2]
# MediaPipe loads its native library and graph resources from its package folder at runtime.
sf_ret = collect_all('_soundfile_data')  # libsndfile for Telegram voice notes
datas += sf_ret[0]; binaries += sf_ret[1]
hiddenimports += ['soundfile', '_soundfile']
# Claude, the online brain: the SDK loads parts of itself lazily (beta streaming, types), so bundle all of it.
zim_ret = collect_all('libzim')  # offline Wikipedia
datas += zim_ret[0]; binaries += zim_ret[1]; hiddenimports += zim_ret[2]
anthropic_ret = collect_all('anthropic')
datas += anthropic_ret[0]; binaries += anthropic_ret[1]; hiddenimports += anthropic_ret[2]
mp_ret = collect_all('mediapipe')
datas += mp_ret[0]; binaries += mp_ret[1]; hiddenimports += mp_ret[2]
# Nova's natural voice (Kokoro): sherpa-onnx's extension loads onnxruntime and its own DLLs from its package folder.
sherpa_ret = collect_all('sherpa_onnx')
datas += sherpa_ret[0]; binaries += sherpa_ret[1]; hiddenimports += sherpa_ret[2]
# Bluetooth heart rate: bleak picks its Windows backend at runtime.
bleak_ret = collect_all('bleak')
datas += bleak_ret[0]; binaries += bleak_ret[1]; hiddenimports += bleak_ret[2]
# Playwright's driver (node + its package) drives Edge for Nova's own browser.
playwright_ret = collect_all('playwright')
datas += playwright_ret[0]; binaries += playwright_ret[1]; hiddenimports += playwright_ret[2]


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
