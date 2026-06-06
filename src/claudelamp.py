#!/usr/bin/env python3
"""ClaudeLamp — Desktop traffic-light indicator for Claude Code.

A miniature floating traffic-light widget that sits on your desktop and
shows Claude Code's real-time working state at a glance.

Uses Tkinter Canvas for the rounded housing + three coloured lamps,
with transparent background so only the traffic light itself is visible.

State mapping:
  🟢 green  → Working (executing tools / thinking)
  🟡 yellow → Needs attention (permission / notification / user choice)
  🔴 red    → Idle (waiting for your next prompt)

Architecture: local HTTP server (127.0.0.1:23335) + Tkinter floating window.
Claude Code hooks push state via PowerShell → HTTP POST → widget update.

Usage:
  python src/claudelamp.py       # foreground (debug)
  pythonw src/claudelamp.py      # background (no console, used by hooks)
"""

import ctypes
import http.server
import json
import os
import queue
import signal
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

# ── Windows DPI awareness ─────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ── Paths ─────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
PID_FILE = REPO_ROOT / ".claudelamp_pid"
CONFIG_FILE = REPO_ROOT / ".claudelamp_config.json"

# ── Constants ─────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = int(os.environ.get("CLAUDELAMP_PORT", "23335"))
TRANSPARENT = "#010101"

SIZE_PRESETS = {
    "small":  (45, 150),
    "medium": (66, 216),
    "large":  (87, 282),
}

LIGHT_ON = {
    "red":    "#F44336",
    "yellow": "#FFC107",
    "green":  "#4CAF50",
}

THEMES = {
    "dark": {
        "label":          "Dark housing",
        "housing_fill":   "#2C2C2C",
        "housing_border": "#1A1A1A",
        "off_red":        "#3D1111",
        "off_yellow":     "#3D2E07",
        "off_green":      "#0D2D0F",
    },
    "light": {
        "label":          "Light housing",
        "housing_fill":   "#E8E8E8",
        "housing_border": "#B0B0B0",
        "off_red":        "#F5C6C6",
        "off_yellow":     "#F5ECD0",
        "off_green":      "#C6E6C8",
    },
}

STATE_TO_ACTIVE = {
    "green":  "green",
    "yellow": "yellow",
    "red":    "red",
    "gray":   None,
}


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _load_config() -> dict:
    cfg = {"theme": "dark", "x": None, "y": None}
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if "width" not in cfg:
        cfg["width"], cfg["height"] = SIZE_PRESETS["medium"]
    return cfg


def _save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ═══════════════════════════════════════════════════════════
# Floating traffic-light window
# ═══════════════════════════════════════════════════════════

class LampWindow:
    """Borderless, always-on-top traffic-light widget.

    Canvas-drawn rounded housing + three flat-colour lamps (no glow rings),
    transparent background so only the traffic-light shape is visible.
    """

    def __init__(self) -> None:
        self._cfg = _load_config()
        self._current_state: str = "gray"
        self._current_theme: str = self._cfg.get("theme", "dark")
        self._drag_x: int = 0
        self._drag_y: int = 0

        # ── Window ────────────────────────────────────────
        self._root = tk.Tk()
        self._root.title("ClaudeLamp")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=TRANSPARENT)
        self._root.wm_attributes("-transparentcolor", TRANSPARENT)

        # ── Canvas ────────────────────────────────────────
        w, h = self._get_size()
        self._canvas = tk.Canvas(
            self._root, width=w, height=h,
            bg=TRANSPARENT, highlightthickness=0, bd=0,
        )
        self._canvas.pack()

        # ── Events ────────────────────────────────────────
        self._canvas.bind("<Button-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_move)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<Button-3>", self._on_right_click)

        # ── Menu ──────────────────────────────────────────
        self._menu = tk.Menu(self._root, tearoff=0)
        self._theme_var = tk.StringVar(value=self._current_theme)
        self._rebuild_menu()

        # ── Position ──────────────────────────────────────
        saved_x = self._cfg.get("x")
        saved_y = self._cfg.get("y")
        if saved_x is not None and saved_y is not None:
            self._root.geometry(f"+{saved_x}+{saved_y}")
        else:
            self._position_bottom_right()

        self._draw()

    # ── Sizing ────────────────────────────────────────────

    def _get_size(self) -> tuple[int, int]:
        return (self._cfg["width"], self._cfg["height"])

    def _get_theme(self) -> dict:
        return THEMES.get(self._current_theme, THEMES["dark"])

    # ── Drawing ───────────────────────────────────────────

    def _draw(self) -> None:
        """Full redraw: rounded housing + three flat lamps."""
        self._canvas.delete("all")
        w, h = self._get_size()
        theme = self._get_theme()

        self._canvas.configure(width=w, height=h)
        self._root.geometry(f"{w}x{h}")

        # Rounded housing
        pad = max(4, int(w * 0.12))
        housing = (pad, pad, w - pad, h - pad)
        corner_r = max(4, int(w * 0.25))
        self._rounded_rect(
            housing, corner_r,
            fill=theme["housing_fill"],
            outline=theme["housing_border"], width=1,
        )

        # Three lamps
        active = STATE_TO_ACTIVE.get(self._current_state)
        off_map = {
            "red": theme["off_red"], "yellow": theme["off_yellow"],
            "green": theme["off_green"],
        }

        usable_top = housing[1] + (housing[3] - housing[1]) * 0.07
        usable_btm = housing[3] - (housing[3] - housing[1]) * 0.07
        spacing = (usable_btm - usable_top) / 3.0
        radius = int(w * 0.17)

        for i, name in enumerate(["red", "yellow", "green"]):
            cy = usable_top + spacing * (i + 0.5)
            cx = w / 2.0
            is_active = (name == active)

            fill = LIGHT_ON[name] if is_active else off_map.get(name, "#1A1A1A")
            outline = "" if is_active else theme["housing_border"]

            self._canvas.create_oval(
                cx - radius, cy - radius,
                cx + radius, cy + radius,
                fill=fill, outline=outline, width=1,
            )

    def _rounded_rect(
        self, bbox: tuple[int, int, int, int], r: int, **kwargs
    ) -> None:
        """Draw a rounded rectangle on the canvas."""
        x1, y1, x2, y2 = bbox
        fill = kwargs.get("fill", "")
        outline = kwargs.get("outline", "")
        width = kwargs.get("width", 1)

        corners = [
            (x1, y1, x1 + 2 * r, y1 + 2 * r, 90),
            (x2 - 2 * r, y1, x2, y1 + 2 * r, 0),
            (x2 - 2 * r, y2 - 2 * r, x2, y2, 270),
            (x1, y2 - 2 * r, x1 + 2 * r, y2, 180),
        ]

        for cx1, cy1, cx2, cy2, start_angle in corners:
            self._canvas.create_arc(
                cx1, cy1, cx2, cy2,
                start=start_angle, extent=90,
                fill=fill, outline="", style="pieslice",
            )
        self._canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
        self._canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
        for cx1, cy1, cx2, cy2, start_angle in corners:
            self._canvas.create_arc(
                cx1, cy1, cx2, cy2,
                start=start_angle, extent=90,
                fill="", outline=outline, width=width, style="arc",
            )
        self._canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
        self._canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
        self._canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
        self._canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)

    # ── Drag ──────────────────────────────────────────────

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x, self._drag_y = event.x, event.y

    def _on_drag_move(self, event: tk.Event) -> None:
        x = self._root.winfo_x() + event.x - self._drag_x
        y = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event: tk.Event) -> None:
        self._cfg["x"], self._cfg["y"] = self._root.winfo_x(), self._root.winfo_y()
        _save_config(self._cfg)

    # ── Right-click menu ──────────────────────────────────

    def _on_right_click(self, event: tk.Event) -> None:
        self._rebuild_menu()
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _rebuild_menu(self) -> None:
        self._menu.delete(0, "end")

        state_label = {
            "green": "Working", "yellow": "Needs attention",
            "red": "Idle", "gray": "Disconnected",
        }.get(self._current_state, self._current_state)
        self._menu.add_command(label=f"Status: {state_label}", state="disabled")
        self._menu.add_separator()

        w, h = self._get_size()
        self._menu.add_command(label=f"Current size: {w}×{h}", state="disabled")
        self._menu.add_command(label="Enlarge (+10%)", command=lambda: self._scale_size(1.10))
        self._menu.add_command(label="Shrink (−10%)", command=lambda: self._scale_size(0.90))
        self._menu.add_separator()

        preset_menu = tk.Menu(self._menu, tearoff=0)
        for key, (pw, ph) in SIZE_PRESETS.items():
            name = {"small": "Small", "medium": "Medium", "large": "Large"}[key]
            preset_menu.add_command(
                label=f"{name} ({pw}×{ph})",
                command=lambda k=key: self._apply_preset(k),
            )
        self._menu.add_cascade(label="Preset size ▸", menu=preset_menu)
        self._menu.add_command(label="Custom size...", command=self._open_custom_dialog)
        self._menu.add_separator()

        self._menu.add_command(label="── Appearance ──", state="disabled")
        for key, info in THEMES.items():
            self._menu.add_radiobutton(
                label=info["label"],
                variable=self._theme_var, value=key,
                command=lambda k=key: self._set_theme(k),
            )
        self._menu.add_separator()
        self._menu.add_command(label="Exit ClaudeLamp", command=self.shutdown)

    # ── Sizing actions ────────────────────────────────────

    def _scale_size(self, factor: float) -> None:
        w = max(20, int(self._cfg["width"] * factor))
        h = max(60, int(self._cfg["height"] * factor))
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._cfg["width"] = min(w, sw // 3)
        self._cfg["height"] = min(h, sh // 2)
        _save_config(self._cfg)
        self._draw()
        self._clamp_to_screen()

    def _apply_preset(self, key: str) -> None:
        if key not in SIZE_PRESETS:
            return
        self._cfg["width"], self._cfg["height"] = SIZE_PRESETS[key]
        _save_config(self._cfg)
        self._draw()
        self._clamp_to_screen()

    def _open_custom_dialog(self) -> None:
        dialog = tk.Toplevel(self._root)
        dialog.title("Custom size")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.transient(self._root)

        w, h = self._get_size()

        tk.Label(dialog, text="Width (px):").grid(
            row=0, column=0, padx=8, pady=6, sticky="e",
        )
        wv = tk.StringVar(value=str(w))
        we = tk.Entry(dialog, textvariable=wv, width=8, justify="center")
        we.grid(row=0, column=1, padx=8, pady=6)
        we.select_range(0, "end")
        we.focus_set()

        tk.Label(dialog, text="Height (px):").grid(
            row=1, column=0, padx=8, pady=6, sticky="e",
        )
        hv = tk.StringVar(value=str(h))
        tk.Entry(dialog, textvariable=hv, width=8, justify="center").grid(
            row=1, column=1, padx=8, pady=6,
        )

        def _apply() -> None:
            try:
                nw, nh = int(wv.get()), int(hv.get())
                if nw < 20 or nh < 60:
                    return
                sw = self._root.winfo_screenwidth()
                sh = self._root.winfo_screenheight()
                self._cfg["width"] = min(nw, sw // 3)
                self._cfg["height"] = min(nh, sh // 2)
                _save_config(self._cfg)
                self._draw()
                self._clamp_to_screen()
            except ValueError:
                pass
            dialog.destroy()

        def _on_key(event: tk.Event) -> None:
            if event.keysym == "Return":
                _apply()
            elif event.keysym == "Escape":
                dialog.destroy()

        dialog.bind("<KeyPress>", _on_key)
        tk.Button(dialog, text="OK", command=_apply, width=8).grid(
            row=2, column=0, columnspan=2, pady=(4, 8),
        )

        x = self._root.winfo_x() + self._cfg["width"] + 10
        y = self._root.winfo_y()
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.wait_window()

    def _set_theme(self, theme: str) -> None:
        if theme not in THEMES or theme == self._current_theme:
            return
        self._current_theme = theme
        self._theme_var.set(theme)
        self._cfg["theme"] = theme
        _save_config(self._cfg)
        self._draw()

    # ── Positioning ───────────────────────────────────────

    def _position_bottom_right(self) -> None:
        w, h = self._get_size()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x, y = sw - w - 20, sh - h - 60
        self._root.geometry(f"+{x}+{y}")
        self._cfg["x"], self._cfg["y"] = x, y
        _save_config(self._cfg)

    def _clamp_to_screen(self) -> None:
        x, y = self._root.winfo_x(), self._root.winfo_y()
        w, h = self._get_size()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = max(10, min(x, sw - w - 10))
        y = max(10, min(y, sh - h - 10))
        self._root.geometry(f"+{x}+{y}")
        self._cfg["x"], self._cfg["y"] = x, y
        _save_config(self._cfg)

    # ── Public API ────────────────────────────────────────

    def update_state(self, state: str) -> None:
        if state not in STATE_TO_ACTIVE or state == self._current_state:
            return
        self._current_state = state
        self._draw()

    def run(self) -> None:
        self._root.mainloop()

    def shutdown(self) -> None:
        try:
            self._root.destroy()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# Application controller
# ═══════════════════════════════════════════════════════════

class ClaudeLampApp:
    """Top-level controller: LampWindow + HTTP state receiver."""

    def __init__(self) -> None:
        self._window: Optional[LampWindow] = None
        self._http_server: Optional[http.server.HTTPServer] = None
        self._running: bool = False
        self._update_queue: queue.Queue[str] = queue.Queue()

    def _create_window(self) -> None:
        self._window = LampWindow()
        self._poll_queue()

    def _poll_queue(self) -> None:
        if self._window is None:
            return
        try:
            while True:
                state = self._update_queue.get_nowait()
                if state == "__SHUTDOWN__":
                    self._window.shutdown()
                    return
                self._window.update_state(state)
        except queue.Empty:
            pass
        self._window._root.after(50, self._poll_queue)

    def enqueue_state(self, state: str) -> None:
        self._update_queue.put(state)

    def request_shutdown(self) -> None:
        self._running = False
        self._update_queue.put("__SHUTDOWN__")

    class _Handler(http.server.BaseHTTPRequestHandler):

        app: "ClaudeLampApp" = None  # type: ignore[assignment]

        def do_POST(self) -> None:
            if self.path == "/state":
                cl = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(cl)
                try:
                    data = json.loads(body)
                    self.app.enqueue_state(data.get("state", ""))
                    self._json(200, {"ok": True, "state": data.get("state", "")})
                except json.JSONDecodeError:
                    self._json(400, {"ok": False, "error": "invalid json"})
            elif self.path == "/shutdown":
                self._json(200, {"ok": True, "bye": True})
                threading.Thread(target=self._delayed_shutdown, daemon=True).start()
            elif self.path == "/ping":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_GET(self) -> None:
            if self.path == "/ping":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def _json(self, code: int, data: dict) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _delayed_shutdown(self) -> None:
            import time
            time.sleep(0.5)
            self.app.request_shutdown()

        def log_message(self, format, *args) -> None:
            pass

    def _start_http(self) -> None:
        self._Handler.app = self
        self._http_server = http.server.HTTPServer((HOST, PORT), self._Handler)
        self._http_server.timeout = 1
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while self._running:
            self._http_server.handle_request()

    def _write_pid(self) -> None:
        try:
            PID_FILE.write_text(str(os.getpid()))
        except OSError:
            pass

    def _cleanup(self) -> None:
        for f in (PID_FILE,):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass

    def run(self) -> None:
        self._write_pid()
        self._running = True
        self._start_http()
        self._create_window()
        self._window.run()
        self._cleanup()


# ═══════════════════════════════════════════════════════════
# Singleton guard
# ═══════════════════════════════════════════════════════════

def kill_existing_instance() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        old_pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(old_pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect((HOST, PORT))
        sock.sendall(
            b"POST /shutdown HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        sock.recv(1024)
        sock.close()
    except Exception:
        try:
            os.kill(old_pid, signal.SIGTERM)
        except OSError:
            pass
    return True


def main() -> None:
    if kill_existing_instance():
        import time
        time.sleep(0.3)
    ClaudeLampApp().run()


if __name__ == "__main__":
    main()
