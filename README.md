# ClaudeLamp

<div align="center">

🟢🟡🔴 **Desktop traffic-light indicator for Claude Code on Windows**

*A miniature floating traffic light that sits on your desktop — instantly visible, never hidden in the tray overflow.*

</div>

## What It Does

ClaudeLamp is a **desktop widget** shaped like a real traffic light. It floats on top of your other windows and changes colour in real time as Claude Code works:

| Lamp | State | Meaning |
|------|-------|---------|
| 🟢 Green | **Working** | Executing tools, thinking, processing your request |
| 🟡 Yellow | **Needs attention** | Permission request, notification, waiting for your choice |
| 🔴 Red | **Idle** | Waiting for your next prompt |

No more alt-tabbing to check if Claude finished — one glance at the corner of your screen tells you everything.

## Quick Start

```powershell
# 1. Clone
git clone https://github.com/yyyg88/ClaudeLamp.git
cd ClaudeLamp

# 2. Install hooks (auto-start with Claude Code)
python install.py

# 3. Restart Claude Code — the lamp appears on your desktop 🟢
```

> **Zero dependencies.** ClaudeLamp uses only Python's built-in `tkinter` — no `pip install` needed.

**Uninstall:**
```powershell
python install.py --remove
```

## Features

- **Floating widget** — always visible, drag to reposition
- **Flexible sizing** — enlarge/shrink (±10%), jump to presets, or enter exact pixels
- **Two themes** — dark housing or light housing (right-click to switch)
- **DPI-aware** — crisp on high-resolution displays
- **Auto start/stop** — launches and exits with Claude Code automatically
- **Zero dependencies** — pure Python standard library

Right-click the lamp for the full menu:

```
Status: Working
─────────────
Current size: 66×216
Enlarge (+10%)
Shrink (−10%)
─────────────
Preset size ▸       Small / Medium / Large
Custom size...       Enter exact W×H
─────────────
── Appearance ──
● Dark housing
○ Light housing
─────────────
Exit ClaudeLamp
```

## How It Works

```
┌─────────────────────┐     hook event      ┌──────────────────┐
│   Claude Code       │ ──────────────────► │  send_state.ps1  │
│   (hooks system)    │                     │  (PowerShell)    │
└─────────────────────┘                     └────────┬─────────┘
                                                     │ HTTP POST
                                                     ▼
┌─────────────────────┐                     ┌──────────────────┐
│   Desktop widget    │ ◄─── tkinter ────── │  claudelamp.py   │
│   🟢🟡🔴 lamp       │                     │  (HTTP server)   │
└─────────────────────┘                     └──────────────────┘
```

1. **Claude Code** fires hook events (`UserPromptSubmit`, `PreToolUse`, `Stop`, …)
2. **send_state.ps1** maps each event to a colour and POSTs to `127.0.0.1:23335`
3. **claudelamp.py** receives the state and redraws the desktop traffic light

All hooks are tagged `[claudelamp]` — safe to coexist with other hook-based tools.

## Requirements

- **Windows 10 / 11**
- **Python 3.9+** with `pythonw.exe` (included in standard installs)
- **Claude Code** (any recent version with hook support)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDELAMP_PORT` | `23335` | HTTP port for state updates |

Set it in your `~/.claude/settings.json` env block if you need a different port.

## Files

```
ClaudeLamp/
├── src/
│   ├── claudelamp.py      # Desktop traffic-light app (Python + tkinter)
│   └── send_state.ps1     # Hook event → HTTP forwarder
├── install.py             # Hook installer / uninstaller
├── LICENSE
└── README.md
```

## Coexists With

ClaudeLamp works side-by-side with other Claude Code hook tools:

- **[Clawd](https://github.com/fansea0/clawd-on-desk)** — desktop pet with idle animations
- **[Claude Traffic Light (Mac)](https://github.com/fansea0/claude-traffic-light)** — the original Mac menu-bar indicator that inspired this project

## License

MIT — see [LICENSE](LICENSE).
