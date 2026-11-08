# PyInstaller recipe for ADDGate.app. Built by ./build_app.sh; you don't run this directly.
# Bundles Python, the backend, the built UI and the hook scripts into one Mac app.
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
BACKEND = os.path.join(ROOT, "backend")

a = Analysis(
    [os.path.join(SPECPATH, "main.py")],
    pathex=[BACKEND],
    datas=[
        (os.path.join(BACKEND, "static"), "static"),  # the built React UI
        (os.path.join(BACKEND, "hooks"), "hooks"),    # copied to ~/gate/hooks on start
    ],
    # gunicorn picks its worker and logger classes by name at runtime, so name them here
    hiddenimports=collect_submodules("gunicorn") + ["app", "flask_sock", "simple_websocket", "wsproto"],
    # macOS uses Cocoa for the window; Linux/Windows toolkits aren't needed in the Mac app
    excludes=["tkinter", "test", "unittest"] + (["gi", "PyQt5", "PyQt6", "qtpy"] if sys.platform == "darwin" else []),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ADDGate",
    console=False,          # a window app, no Terminal window
    argv_emulation=False,
    codesign_identity=None,  # ad-hoc signed: fine for apps you build on your own Mac
)
coll = COLLECT(exe, a.binaries, a.datas, name="ADDGate")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ADDGate.app",
        icon=os.path.join(SPECPATH, "ADDGate.icns"),
        bundle_identifier="dev.addgate.desktop",
        info_plist={
            "CFBundleName": "ADDGate",
            "CFBundleDisplayName": "ADDGate",
            "CFBundleShortVersionString": "2.8",
            "CFBundleVersion": "2.8",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            # the window loads the app from http://127.0.0.1:5055 on this Mac only
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
