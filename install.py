#!/usr/bin/env python3
"""ClaudeLamp hook installer / uninstaller.

Adds or removes ClaudeLamp hooks from ``~/.claude/settings.json`` so that the
traffic light starts, updates, and stops automatically with Claude Code.

Usage:
  python install.py               # install
  python install.py --remove      # uninstall
  python install.py --dry-run     # preview changes without writing

All hooks are tagged with ``[claudelamp]`` — safe to mix with other hooks.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Path resolution ───────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
SEND_STATE_PS1 = SRC_DIR / "send_state.ps1"
CLAUDELAMP_PY = SRC_DIR / "claudelamp.py"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

TAG = "[claudelamp]"

# ── Python discovery ──────────────────────────────────────

def _find_pythonw() -> Optional[str]:
    """Locate pythonw.exe (no-console launcher) on this machine."""
    # 1. Same directory as the current Python interpreter
    candidates = []
    exe = Path(sys.executable)
    if exe.stem == "python":
        pw = exe.with_name("pythonw.exe")
        if pw.exists():
            candidates.append(str(pw))
    # 2. via ``where pythonw``
    try:
        result = subprocess.run(
            ["where", "pythonw"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().splitlines():
            p = Path(line.strip())
            if p.exists():
                candidates.append(str(p))
    except Exception:
        pass
    # 3. Common Conda / venv locations
    for base in [Path(sys.prefix), Path.home() / "miniconda3", Path.home() / "anaconda3"]:
        pw = base / "pythonw.exe"
        if pw.exists():
            candidates.append(str(pw))
    # Return the first match (prefer same-env)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

# ── Hook generators ───────────────────────────────────────

def _launch_hook(pythonw_path: str) -> dict:
    return {
        "type": "command",
        "shell": "powershell",
        "command": (
            f'Start-Process -WindowStyle Hidden '
            f'-FilePath "{pythonw_path}" '
            f'-ArgumentList "{CLAUDELAMP_PY}"  # {TAG}'
        ),
        "async": True,
        "timeout": 5,
    }

def _send_state_hook(event: str) -> dict:
    return {
        "type": "command",
        "shell": "powershell",
        "command": f'& "{SEND_STATE_PS1}" -Event {event}  # {TAG}',
        "async": True,
        "timeout": 3,
    }

def _is_claudelamp_hook(hook: dict) -> bool:
    return TAG in hook.get("command", "")

# ── Events to wire ────────────────────────────────────────
EVENTS = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "Notification",
    "PermissionRequest",
    "Elicitation",
]


def _install(settings: dict, pythonw_path: str) -> int:
    hooks_section = settings.setdefault("hooks", {})
    added = 0

    for event in EVENTS:
        entries = hooks_section.setdefault(event, [])
        if not entries:
            entries.append({"matcher": "", "hooks": []})
        for entry in entries:
            existing = entry.get("hooks", [])
            if any(_is_claudelamp_hook(h) for h in existing):
                print(f"  [skip] {event} — already installed")
                continue
            existing.append(_send_state_hook(event))
            added += 1

    # SessionStart: also launch the server (before state update)
    ss_entries = hooks_section.setdefault("SessionStart", [])
    if not ss_entries:
        ss_entries.append({"matcher": "", "hooks": []})
    for entry in ss_entries:
        existing = entry.get("hooks", [])
        if not any("claudelamp.py" in h.get("command", "") for h in existing):
            existing.insert(0, _launch_hook(pythonw_path))
            added += 1

    return added


def _remove(settings: dict) -> int:
    hooks_section = settings.get("hooks", {})
    removed = 0

    for event, entries in list(hooks_section.items()):
        for entry in entries:
            hooks = entry.get("hooks", [])
            new_hooks = [h for h in hooks if not _is_claudelamp_hook(h)]
            diff = len(hooks) - len(new_hooks)
            if diff > 0:
                entry["hooks"] = new_hooks
                removed += diff

        # Prune empty groups
        hooks_section[event] = [
            e for e in entries if e.get("hooks") or e.get("matcher") != ""
        ]
        if not hooks_section[event]:
            del hooks_section[event]

    return removed


# ── Main ──────────────────────────────────────────────────

def main() -> None:
    dry_run = "--dry-run" in sys.argv
    remove = "--remove" in sys.argv

    if not SETTINGS_PATH.exists():
        print(f"Error: settings.json not found at {SETTINGS_PATH}")
        print("Make sure Claude Code has been launched at least once.")
        sys.exit(1)

    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    if remove:
        n = _remove(settings)
        action = "would remove" if dry_run else "removed"
        print(f"[{'dry-run' if dry_run else 'done'}] {action} {n} hook(s)")
    else:
        pythonw_path = _find_pythonw()
        if pythonw_path is None:
            print("Error: could not locate pythonw.exe")
            print("Install Python 3.9+ from https://python.org or use conda.")
            sys.exit(1)
        print(f"  pythonw  → {pythonw_path}")
        print(f"  settings → {SETTINGS_PATH}")
        n = _install(settings, pythonw_path)
        action = "would add" if dry_run else "added"
        print(f"[{'dry-run' if dry_run else 'done'}] {action} {n} hook(s)")

    if not dry_run:
        SETTINGS_PATH.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not remove:
            print("\nClaudeLamp will start automatically with Claude Code.")


if __name__ == "__main__":
    main()
