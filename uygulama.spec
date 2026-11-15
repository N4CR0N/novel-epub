# PyInstaller tarifi: tek dosyalık, pencereli Windows exe'si (GitHub Actions derler).
# Boyut için: kullanılmayan paketler ve Windows 10/11'de zaten bulunan UCRT DLL'leri pakete konmaz.
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

datas = [("novel_epub/templates", "novel_epub/templates")] + collect_data_files("certifi") + copy_metadata("keyring")
binaries, hidden = [], [m for m in collect_submodules("keyring") if ".testing" not in m]
for pkg in ("curl_cffi", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += [m for m in h if "__pyinstaller" not in m and ".tests" not in m]

EXCLUDES = [
    "tkinter", "unittest", "test", "pydoc_data", "setuptools", "pip", "lib2to3", "idlelib", "ensurepip",
    # keyring.testing → pytest → pygments zinciri ve derleme araçları (çalışırken hiç kullanılmaz)
    "keyring.testing", "pytest", "_pytest", "pygments", "pluggy", "iniconfig", "PyInstaller", "pefile",
    "doctest", "pydoc",
]

a = Analysis(
    ["uygulama.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)


def _keep(entry) -> bool:
    name = entry[0].replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    if base.startswith("api-ms-win-") or base == "ucrtbase.dll":  # Windows 10+ içinde var
        return False
    # WebView2Loader'ın ARM64/x86 kopyaları atılmaz: pywebview açılışta üçünü de arar (yoksa uygulama açılmaz)
    return True


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WebNovelDownloaderTranslator",
    icon="assets/icon.ico",
    console=False,
    upx=False,  # UPX antivirüslerde yanlış alarma yol açıyor; 2 MB'lık kazanç buna değmez
    runtime_tmpdir=None,
)
