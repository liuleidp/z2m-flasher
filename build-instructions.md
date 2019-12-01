# macOS

`pyinstaller -F -w -n Z2M-Flasher -i icon.icns z2mflasher/__main__.py`

# Windows

1. Start up VM
2. Install Python (3) from App Store
3. Download z2m-flasher from GitHub
4. `pip install -e.` and `pip install pyinstaller`
5. Check with `python -m z2mflasher.__main__`
6. `python -m PyInstaller.__main__ -F -w -n Z2M-Flasher -i icon.ico --add-data z2mflasher\tools\mkspiffs\win\mkspiffs.exe;tools\mkspiffs\win z2mflasher\__main__.py`
7. Go to `dist` folder, check Z2M-Flasher.exe works.
