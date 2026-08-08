# CAD Gesture

A mouse gesture + radial pie menu tool for **AutoCAD** and **ZWCAD**.
Press and hold the **right mouse button** and drag inside CAD to pick a command from the radial menu and execute it — no need to memorize shortcuts. Built-in preset profiles, ready to use out of the box, designed for fast drawing scenarios such as CAD drawing competitions.

## Features

- **Three-ring radial menu**: 8 sectors × 3 rings, with inner / outer / extension rings organizing commands by frequency
- **Smooth gesture interaction**: hold to summon, release to trigger; hover highlight with fade-in animation
- **Multiple profiles**: separate configs for different CAD apps / workflows, auto-switched by foreground window
- **6 menu themes**: Azure / Emerald / Crimson / Midnight / Aurora / Graphite
- **Visual config UI** (CustomTkinter): click a sector to edit its command, searchable command library with drag & drop
- **No interference with CAD operations**: commands are sent via COM `SendCommand`; the hook only listens, never blocks
- **Single instance**: relaunching replaces the old instance

## Requirements

- Windows 10 / 11 (64-bit)
- AutoCAD 2025+ or ZWCAD
- Python 3.11+ (when running from source)

## Quick Start

### Option 1: Packaged build

1. Download `CADGesture.exe` from the latest [Release](https://github.com/Inonvation/cad-gesture/releases)
2. Double-click to run; the app is ready once the tray icon appears
3. Open CAD, **press and hold the right mouse button and drag** to use

> If no installer is available in Releases yet, use Option 2 instead.

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
| Tray icon | Right-click → config / switch profile / quit |

## Configuration

Right-click the tray icon → **Config** to open the visual editor:

- **Left**: profile management (new / duplicate / rename / delete)
- **Center**: radial menu preview; click a sector to edit its command
- **Right**: command library with search and drag & drop
- **Sidebar**: menu theme, startup options

Config is stored in `config/config.json` (auto-generated with defaults on first run; template: `config/config.example.json`). Each profile contains three rings of commands: `sectors` (inner), `outer_sectors` (outer), `extension_sectors` (extension). Each command consists of `label` (display name), `key` (fallback shortcut), and `description` (CAD command name).

## Tech Stack

- **Python 3.11+** / Win32 API (low-level mouse hook `WH_MOUSE_LL`, Per-Monitor V2 DPI awareness)
- **CustomTkinter** (config UI)
- **COM / pyautogui** (command execution)
- **pystray / Pillow** (tray icon)
- **PyInstaller** (packaging)

## Project Structure

```
main.py                  # Entry point (single-instance check + DPI awareness)
requirements.txt         # Dependencies
config/                  # Config (auto-generated on first run; template: config.example.json)
src/                     # Source code
├── app.py               # Main app: event queue, tray, config entry
├── gesture_engine.py    # Mouse hook, gesture / ring detection
├── radial_menu.py       # Transparent overlay radial menu
├── command_executor.py  # COM command execution + fallback
├── config_gui.py        # Config UI
└── ...                  # Rendering, themes, logging, single-instance, etc.
assets/                  # App icon
tests/                   # Unit tests
```

This project is **independently developed**. Inspired by the mouse gestures in Quicker and SolidWorks, it is a first attempt at building a Python desktop app with AI assistance. Built in spare time with limited resources, so issues and PRs are welcome. Thanks for using it!
