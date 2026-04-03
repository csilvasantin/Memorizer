#!/usr/bin/env python3
"""Memorizer menu bar app — runs the bot and shows status in macOS menu bar."""

import subprocess
import sys
import os
import threading
import time

import rumps

MEMORIZER_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = "/usr/local/bin/python3.13"
STATUS_KEY = "status"


class MemorizerApp(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)
        self.status_item = rumps.MenuItem(STATUS_KEY, callback=None)
        self.status_item.title = "Memorizer: arrancando..."
        self.menu = [
            self.status_item,
            None,
            rumps.MenuItem("Reiniciar", callback=self.restart_bot),
            rumps.MenuItem("Detener", callback=self.stop_bot),
            None,
            rumps.MenuItem("Salir", callback=self.quit_app),
        ]
        self.bot_process = None
        self.log_lines = []
        self._start_bot()

    def _start_bot(self):
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self.log_file = open(os.path.join(MEMORIZER_DIR, "data", "bot.log"), "a")
        self.bot_process = subprocess.Popen(
            [PYTHON, "-m", "src.bot"],
            cwd=MEMORIZER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        self.title = "🧠"
        self.status_item.title = "Memorizer: corriendo ✅"
        threading.Thread(target=self._monitor_output, daemon=True).start()

    def _monitor_output(self):
        proc = self.bot_process
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self.log_lines.append(text)
                self.log_lines = self.log_lines[-50:]
                self.log_file.write(text + "\n")
                self.log_file.flush()
                if "Processing message" in text:
                    self.title = "🧠✨"
                    threading.Timer(2.0, self._reset_icon).start()
        # Process ended
        self.title = "🧠💀"
        self.status_item.title = "Memorizer: detenido ❌"

    def _reset_icon(self):
        if self.bot_process and self.bot_process.poll() is None:
            self.title = "🧠"

    @rumps.clicked("Reiniciar")
    def restart_bot(self, _):
        self._kill_bot()
        time.sleep(1)
        self._start_bot()
        rumps.notification("Memorizer", "", "Bot reiniciado ✅")

    @rumps.clicked("Detener")
    def stop_bot(self, _):
        self._kill_bot()
        self.title = "🧠💤"
        self.status_item.title = "Memorizer: detenido ❌"
        rumps.notification("Memorizer", "", "Bot detenido")

    def _kill_bot(self):
        if self.bot_process and self.bot_process.poll() is None:
            self.bot_process.terminate()
            try:
                self.bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.bot_process.kill()

    @rumps.clicked("Salir")
    def quit_app(self, _):
        self._kill_bot()
        rumps.quit_application()


if __name__ == "__main__":
    MemorizerApp().run()
