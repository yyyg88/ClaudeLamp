#!/usr/bin/env python3
"""ClaudeLamp — Windows system-tray indicator for Claude Code.

A traffic-light indicator that lives in your Windows system tray, driven by
Claude Code hook events. It shows Claude Code's real-time working state:

  🟢 green  → idle (waiting for input)
  🟡 yellow → thinking (processing your request)
  🔴 red    → working (executing tools / error)

Architecture: local HTTP server (127.0.0.1:23335) + pystray icon.
Claude Code hooks push state via PowerShell → HTTP POST → icon update.

Usage:
  python src/claudelamp.py       # foreground (debug)
  pythonw src/claudelamp.py      # background (no console, used by hooks)
"""

import http.server
import json
import os
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import Optional

# ── Third-party ───────────────────────────────────────────
from PIL import Image, ImageDraw
import pystray

# ── Constants ─────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = int(os.environ.get("CLAUDELAMP_PORT", "23335"))
ICON_SIZE = 64

COLORS: dict[str, tuple[int, int, int]] = {
    "green":  (76, 175, 80),    # Material Green 500
    "yellow": (255, 193, 7),    # Material Amber 500
    "red":    (244, 67, 54),    # Material Red 500
    "gray":   (158, 158, 158),  # Material Grey 500 (starting / disconnected)
}

STATE_LABELS: dict[str, str] = {
    "green":  "Idle",
    "yellow": "Thinking",
    "red":    "Working",
    "gray":   "Disconnected",
}

PID_FILE = Path(__file__).resolve().parent.parent / ".claudelamp_pid"


# ── Icon drawing ──────────────────────────────────────────

def make_icon_image(color_name: str) -> Image.Image:
    """Draw a 64×64 RGBA circle icon with shadow and highlight.

    Args:
        color_name: One of ``green``, ``yellow``, ``red``, ``gray``.

    Returns:
        A Pillow RGBA Image ready for pystray.
    """
    r, g, b = COLORS.get(color_name, COLORS["gray"])
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 4
    # Shadow ring (semi-transparent black)
    draw.ellipse(
        [margin - 1, margin - 1, ICON_SIZE - margin + 1, ICON_SIZE - margin + 1],
        fill=(0, 0, 0, 60),
    )
    # Main filled circle
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        fill=(r, g, b, 255),
    )
    # Top highlight (simulates 3D glass effect)
    hi = margin + 6
    draw.ellipse(
        [hi, hi, ICON_SIZE - hi, ICON_SIZE - hi - 6],
        fill=(255, 255, 255, 40),
    )
    return img


# ── Tray application ──────────────────────────────────────

class ClaudeLampApp:
    """System-tray traffic light for Claude Code.

    Runs a pystray icon in the main thread and a minimal HTTP server in a
    daemon thread. Hook events arrive as ``POST /state`` and update the icon
    colour and tooltip in real time.
    """

    def __init__(self) -> None:
        self._current_state: str = "gray"
        self._icon: Optional[pystray.Icon] = None
        self._http_server: Optional[http.server.HTTPServer] = None
        self._lock = threading.Lock()
        self._running = True

        # Pre-render all colour variants
        self._icons: dict[str, Image.Image] = {
            name: make_icon_image(name) for name in COLORS
        }

    # ── Tray icon ──────────────────────────────────────────

    def _build_menu(self) -> pystray.Menu:
        """Build the right-click context menu."""
        return pystray.Menu(
            pystray.MenuItem(
                f"Status: {STATE_LABELS[self._current_state]}",
                lambda: None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit ClaudeLamp", self._on_exit),
        )

    def _create_tray_icon(self) -> pystray.Icon:
        icon = pystray.Icon(
            "claudelamp",
            self._icons["gray"],
            "ClaudeLamp — Idle",
            menu=self._build_menu(),
        )
        return icon

    def _update_icon(self, state: str) -> None:
        """Thread-safe icon + tooltip + menu update."""
        if state not in COLORS:
            return

        with self._lock:
            if state == self._current_state:
                return
            self._current_state = state

        if self._icon is None:
            return

        try:
            self._icon.icon = self._icons[state]
            self._icon.title = f"ClaudeLamp — {STATE_LABELS[state]}"
            self._icon.update_menu()
        except Exception:
            pass

    def _on_exit(self, icon: pystray.Icon) -> None:
        self.shutdown()

    # ── HTTP server ────────────────────────────────────────

    class _Handler(http.server.BaseHTTPRequestHandler):
        """Lightweight HTTP handler for state updates.

        Endpoints:
          POST /state     — set lamp colour  ``{"state": "green"|"yellow"|"red"}``
          POST /shutdown  — gracefully stop the app
          GET  /ping      — health check, returns current state
        """

        app: "ClaudeLampApp" = None  # type: ignore[assignment]

        def do_POST(self) -> None:
            if self.path == "/state":
                self._handle_state()
            elif self.path == "/shutdown":
                self._handle_shutdown()
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_GET(self) -> None:
            if self.path == "/ping":
                self._json(200, {"ok": True, "state": self.app._current_state})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def _handle_state(self) -> None:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                state = data.get("state", "")
                self.app._update_icon(state)
                self._json(200, {"ok": True, "state": state})
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "error": "invalid json"})

        def _handle_shutdown(self) -> None:
            self._json(200, {"ok": True, "bye": True})
            threading.Thread(target=self._delayed_shutdown, daemon=True).start()

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
            self.app.shutdown()

        def log_message(self, format, *args) -> None:
            pass  # suppress HTTP access logs

    def _start_http(self) -> None:
        self._Handler.app = self
        self._http_server = http.server.HTTPServer((HOST, PORT), self._Handler)
        self._http_server.timeout = 1
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while self._running:
            self._http_server.handle_request()

    # ── Lifecycle ──────────────────────────────────────────

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
        self._start_http()
        self._icon = self._create_tray_icon()

        signal.signal(signal.SIGINT, lambda *_: self.shutdown())
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown())

        try:
            self._icon.run()
        except Exception:
            pass
        finally:
            self._cleanup()

    def shutdown(self) -> None:
        self._running = False
        self._cleanup()
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass


# ── Singleton guard ───────────────────────────────────────

def kill_existing_instance() -> bool:
    """Kill a previous ClaudeLamp instance if one is running."""
    if not PID_FILE.exists():
        return False

    try:
        old_pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False

    # Check the process still exists
    try:
        os.kill(old_pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return False

    # Graceful shutdown via HTTP
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


# ── Entry point ───────────────────────────────────────────

def main() -> None:
    if kill_existing_instance():
        import time
        time.sleep(0.3)

    ClaudeLampApp().run()


if __name__ == "__main__":
    main()
