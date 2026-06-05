# ClaudeLamp

<div align="center">

🟢🟡🔴 **Real-time traffic-light indicator for Claude Code on Windows**

*A tiny system-tray app that shows what Claude Code is doing — idle, thinking, or working — at a glance.*

</div>

## What It Does

ClaudeLamp lives in your Windows system tray and changes colour based on Claude Code's activity:

| Colour | State | Meaning |
|--------|-------|---------|
| 🟢 Green | Idle | Waiting for your next prompt |
| 🟡 Yellow | Thinking | Processing your request, reasoning |
| 🔴 Red | Working | Executing tools, running code, or handling errors |

It starts and stops **automatically** with Claude Code — no manual clicks, no hotkeys.

## Quick Start

```powershell
# 1. Clone
git clone https://github.com/yyyg88/claudelamp.git
cd ClaudeLamp

# 2. Install dependencies
pip install pystray Pillow

# 3. Install hooks (auto-start with Claude Code)
python install.py

# 4. Restart Claude Code — the lamp appears in your tray 🟢
```

**Uninstall:**
```powershell
python install.py --remove
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
│   Windows Tray      │ ◄─── pystray ────── │  claudelamp.py   │
│   🟢🟡🔴 icon       │                     │  (HTTP server)   │
└─────────────────────┘                     └──────────────────┘
```

1. **Claude Code** fires hook events (SessionStart, UserPromptSubmit, Stop, …)
2. **send_state.ps1** maps each event to a colour and POSTs to `127.0.0.1:23335`
3. **claudelamp.py** receives the state, updates the system-tray icon in real time

All hooks are tagged ``[claudelamp]`` and coexist safely with other hook-based tools.

## Requirements

- **Windows 10 / 11**
- **Python 3.9+** with `pythonw.exe` (included by default)
- **Claude Code** (any recent version with hook support)
- `pystray` + `Pillow` (`pip install pystray Pillow`)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDELAMP_PORT` | `23335` | HTTP port for state updates |

Set it in your `~/.claude/settings.json` env block if you need a different port.

## Files

```
ClaudeLamp/
├── src/
│   ├── claudelamp.py      # System-tray app (Python + pystray)
│   └── send_state.ps1     # Hook event → HTTP forwarder
├── install.py             # Hook installer / uninstaller
├── LICENSE
└── README.md
```

## Coexists With

ClaudeLamp works side-by-side with other Claude Code hook tools:

- **[Clawd](https://github.com/fansea0/clawd-on-desk)** — desktop pet with animations
- **[Claude Traffic Light (Mac)](https://github.com/fansea0/claude-traffic-light)** — the original Mac menu-bar indicator that inspired this project

## License

MIT — see [LICENSE](LICENSE).
