## Running the Bot

```bash
# Install dependencies (first time)
npm install
pip install -r requirements.txt

# Start (Linux/CachyOS — requires frida-server running in Wine first)
FRIDA_REMOTE=127.0.0.1:27042 npm start

# Start frida-server in Wine (separate terminal, keep running)
WINEPREFIX=~/.local/share/Steam/steamapps/compatdata/3224770/pfx \
  "$HOME/.local/share/Steam/steamapps/common/Proton - Experimental/files/bin/wine" \
  ~/frida-server-17.9.1-windows-x86_64.exe

WINEPREFIX=~/.local/share/Steam/steamapps/compatdata/3224770/pfx \
  "$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton10-34/files/bin/wine" \
  ~/frida-server-17.9.1-windows-x86_64.exe

# Capture game API calls for reverse engineering
FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python capture_dailies.py output.json

# Test Frida attach only (game must be running)
FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python test_frida.py
```

**Static data:** `data/*.json` — `race_map.json`, `skill_data.json`, `factor_map.json` are large reference files loaded at startup. `master_data.py` reads `master.mdb` from the game's Proton prefix (`~/.steam/steam/steamapps/compatdata/3224770/pfx/...`) and generates derived JSON files.