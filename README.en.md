# CAD Gesture

A mouse gesture + radial pie menu tool for **AutoCAD** and **ZWCAD**.
Press and hold the **right mouse button** and drag inside CAD to pick a command from the radial menu and execute it — no need to memorize shortcuts. Built-in preset profiles, ready to use out of the box, designed for fast drawing scenarios such as CAD drawing competitions.

## Features

- **Three-ring radial menu**: 8 sectors × 3 rings, with inner / outer / extension rings organizing commands by frequency
- **Smooth gesture interaction**: hold to summon, release to trigger; hover highlight with fade-in animation
- **Multiple profiles**: separate configs for different CAD apps / workflows, auto-switched by foreground window
- **6 menu themes**: Azure / Emerald / Crimson / Midnight / Aurora / Graphite
- **Modern dark config UI** (PySide6/Qt): three-column draggable layout, command library with drag & drop onto the radial menu, Delete to remove, undo/redo (Ctrl+Z / Ctrl+Y)
- **No interference with CAD operations**: commands are sent via COM `SendCommand`; the hook only listens, never blocks
- **Single instance**: relaunching replaces the old instance
- **One-click update**: check for updates from the tray menu or automatically at startup; downloads the new version and installs it silently

## Requirements

- Windows 10 / 11 (64-bit)
- AutoCAD 2025+ or ZWCAD
- Python 3.11+ (when running from source)

## Quick Start

### Option 1: Packaged build

Two forms are available (config is stored in `%APPDATA%`, so both forms are interchangeable):

| Form | File | Notes |
|------|------|-------|
| Installer (recommended) | `Setup-CADGesture-vX.Y.Z.exe` | Standard install wizard, Start Menu / uninstall entry, supports in-app one-click update |
| Portable | `CADGesture-vX.Y.Z.zip` | No install needed; unzip and run `CADGesture-x64.exe` |

1. Download either form from the latest [Release](https://github.com/Inonvation/cad-gesture/releases)
2. Installer: double-click to run. Portable: unzip the archive first, then run `CADGesture-x64.exe`; the app is ready once the tray icon appears
3. Open CAD, **press and hold the right mouse button and drag** to use

> **SmartScreen warning?** The binaries are unsigned, so Windows may show "Unknown publisher". Click "More info" → "Run anyway" — the app is open source and safe.

### Option 2: Run from source

```powershell
# Install dependencies (Windows)
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Run
python main.py
```

## Usage

| Action | Description |
|--------|-------------|
| Open menu | Press and hold the right mouse button and drag inside the CAD window (~80ms) |
| Select command | Drag toward the target sector, release once highlighted |
| Inner ring | High-frequency drawing commands (line, circle, copy, etc.) |
| Outer ring | Editing commands (arc, rotate, scale, etc.) |
| Extension ring | Low-frequency extension commands, triggered past the second ring boundary |
| Tray icon | Right-click → config / check for updates / switch profile / quit |

## Auto Update

- **Check for updates**: tray menu → "Check for updates" queries the latest release immediately; if a new version exists, click "Update now" to download and install it silently
- **Auto-check at startup**: enabled by default (toggle in Settings), runs silently in the background at most once per 24 hours
- Updates never touch your config: it lives in `%APPDATA%\CADGesture`, independent of the install directory

## Configuration

Right-click the tray icon → **Config** to open the visual editor:

- **Left**: profile management (new / duplicate / rename / delete / settings)
- **Center**: radial menu preview; click a sector to edit its command, hover to highlight, right-click a command then click a sector to place it
- **Right**: command library with search, left-click to apply to the selected sector, right-click or drag & drop to place onto the disc
- **Settings**: menu theme, opacity, trigger sensitivity, disc size, startup options

Config is stored in `config/config.json` (auto-generated with defaults on first run; template: `config/config.example.json`). Each profile contains three rings of commands: `sectors` (inner), `outer_sectors` (outer), `extension_sectors` (extension). Each command consists of `label` (display name), `key` (fallback shortcut), and `description` (CAD command name).

## Tech Stack

- **Python 3.11+** / Win32 API (low-level mouse hook `WH_MOUSE_LL`, Per-Monitor V2 DPI awareness)
- **PySide6 / Qt 6** (GUI: system tray, transparent radial menu, config UI)
- **COM / pyautogui** (command execution)
- **PyInstaller** (packaging)

## Project Structure

```
main.py                  # Entry point (single-instance check + DPI awareness)
requirements.txt         # Dependencies
cad_gesture.iss          # Inno Setup script (builds Setup-CADGesture-vX.Y.Z.exe)
config/                  # Config (auto-generated on first run; template: config.example.json)
src/                     # Source code
├── app.py               # Main app: event queue, tray, config entry, update flow
├── gesture_engine.py    # Mouse hook, gesture / ring detection
├── qt_radial_menu.py    # Qt transparent overlay radial menu
├── qt_renderer.py       # Shared Qt disc drawing (runtime + config preview)
├── command_executor.py  # COM command execution + fallback
├── qt_config_gui.py     # Qt config UI
├── theme.py             # UI colors + 6 disc appearance themes
├── updater.py           # Auto update (check / download / silent install)
├── version.py           # Runtime version (kept in sync with version.txt)
└── ...                  # Config manager, presets, logging, single-instance, etc.
scripts/                 # Dev scripts (build.bat, verify, icon generator)
assets/                  # App icon
tests/                   # Unit tests
```

This project is **independently developed**. Inspired by the mouse gestures in Quicker and SolidWorks, it is a first attempt at building a Python desktop app with AI assistance. Built in spare time with limited resources, so issues and PRs are welcome. Thanks for using it!
