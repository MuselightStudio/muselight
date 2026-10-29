"""Runs the Credits server on this PC for testing the web app: fal key from the Windows app's saved keys, data in
muselight_cloud/data/local (git-ignored). The site served on localhost:5500 talks to it at 127.0.0.1:8080.

    python tools/local_api.py                      start it
    python tools/local_api.py credit <acct> 5 test  add $5 to a local test account
"""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from providers import _core as core

os.environ.update(FAL_KEY=core.key("FAL_KEY"), DATA_DIR=str(ROOT / "muselight_cloud" / "data" / "local"), PORT="8080",
                  ALLOWED_ORIGINS="http://localhost:5500,http://127.0.0.1:5500")
os.chdir(ROOT / "muselight_cloud")
sys.argv = ["server.py"] + sys.argv[1:]
runpy.run_path("server.py", run_name="__main__")
