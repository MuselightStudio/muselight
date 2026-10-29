@echo off
rem Rebuilds Muselight.exe from the source files in this folder.
rem (Paths are absolute because PyInstaller reads them relative to its temp build folder.)
rem Needs: python -m pip install pyinstaller anthropic "mcp[cli]" keyring pillow
cd /d "%~dp0"
python studio.py --selftest || (echo Self-test failed, not building. & pause & exit /b 1)
python -m PyInstaller --noconfirm --onefile --noconsole --name "Muselight" --icon "%~dp0muselight.ico" ^
  --add-data "%~dp0studio_ui.html;." --add-data "%~dp0AGENT_GUIDE.md;." --add-data "%~dp0muselight.ico;." --add-data "%~dp0icons;icons" --add-data "%~dp0studio_data\models.json;." --add-data "%~dp0studio_data\params.json;." --add-data "%~dp0providers\catalogs;providers\catalogs" --add-data "%~dp0providers\comfy_starters;providers\comfy_starters" ^
  --paths "%~dp0." --hidden-import agent --hidden-import fal_mcp --hidden-import fal_run --hidden-import wintaskbar --collect-submodules providers ^
  --collect-submodules mcp --collect-submodules keyring --hidden-import keyring.backends.Windows --collect-submodules anthropic ^
  --workpath "%TEMP%\muselight_build" --specpath "%TEMP%\muselight_build" --distpath . "%~dp0studio.py"
copy /y Muselight.exe download\Muselight.exe >nul
python tools\refresh_icon_cache.py
echo.
echo Done: Muselight.exe
pause
