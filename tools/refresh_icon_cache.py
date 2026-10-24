"""After a build: if the app icon changed since the last build, make Windows forget its cached copy.

Windows keeps its own copy of every program's icon and rarely notices a new one, so the exe and the taskbar keep showing the
old icon. This clears that copy and restarts Explorer (the taskbar blinks for a few seconds), so it only runs when the icon
actually changed. Run by build_exe.bat; `python tools/refresh_icon_cache.py --force` does it regardless.
"""
import hashlib, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICO, MARK = ROOT / "muselight.ico", Path(__file__).with_name(".icon_hash")

h = hashlib.sha256(ICO.read_bytes()).hexdigest()
if MARK.exists() and MARK.read_text().strip() == h and "--force" not in sys.argv:
    print("Icon unchanged: Windows icon cache left alone.")
    sys.exit()
if sys.platform == "win32":
    local = Path(os.environ["LOCALAPPDATA"])
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True)
    time.sleep(2)
    for f in [local / "IconCache.db", *(local / "Microsoft" / "Windows" / "Explorer").glob("iconcache_*.db")]:
        try:
            f.unlink()
        except OSError:
            pass  # in use: Explorer rebuilds it anyway
    subprocess.Popen(["explorer.exe"])
    time.sleep(3)
    subprocess.run(["ie4uinit.exe", "-show"], capture_output=True)
MARK.write_text(h)
print("Icon changed: cleared Windows' icon cache so the exe and taskbar show the new one.")
