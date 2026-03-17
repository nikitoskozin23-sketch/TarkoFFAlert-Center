from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional


class BackendManager:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self._log_lines: list[str] = []
        self._log_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self.host = "127.0.0.1"
        self.port = 8765

    # -------------------------------------------------------------------------
    # paths / commands
    # -------------------------------------------------------------------------

    def _project_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    def _backend_command(self) -> tuple[list[str], Path]:
        root = self._project_root()

        # Режим после сборки в exe
        if getattr(sys, "frozen", False):
            backend_exe = root / "backend" / "backend.exe"
            return [str(backend_exe)], backend_exe.parent

        # Режим разработки
        backend_python = root / "backend" / ".venv" / "Scripts" / "python.exe"
        backend_script = root / "backend" / "main.py"
        return [str(backend_python), str(backend_script)], root

    # -------------------------------------------------------------------------
    # state
    # -------------------------------------------------------------------------

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def get_overlay_url(self) -> str:
        return f"http://{self.host}:{self.port}/overlay"

    def get_control_url(self) -> str:
        return f"http://{self.host}:{self.port}/control"

    # -------------------------------------------------------------------------
    # logs
    # -------------------------------------------------------------------------

    def _append_log(self, text: str) -> None:
        if not text:
            return
        with self._log_lock:
            self._log_lines.append(text.rstrip("\n"))
            self._log_lines = self._log_lines[-5000:]

    def get_logs(self) -> str:
        with self._log_lock:
            return "\n".join(self._log_lines)

    def get_logs_text(self) -> str:
        return self.get_logs()

    def clear_logs(self) -> None:
        with self._log_lock:
            self._log_lines.clear()

    def _reader_loop(self) -> None:
        if self.process is None or self.process.stdout is None:
            return

        try:
            for line in self.process.stdout:
                if not line:
                    break
                self._append_log(line.rstrip("\n"))
        except Exception as e:
            self._append_log(f"[reader-error] {e}")

    # -------------------------------------------------------------------------
    # health checks
    # -------------------------------------------------------------------------

    def _wait_until_online(self, timeout: float = 15.0) -> bool:
        import requests

        url = f"http://{self.host}:{self.port}/api/health"
        deadline = time.time() + timeout

        session = requests.Session()
        session.trust_env = False

        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False

            try:
                resp = session.get(url, timeout=1.5)
                if resp.ok:
                    return True
            except Exception:
                pass

            time.sleep(0.4)

        return False

    # -------------------------------------------------------------------------
    # process control
    # -------------------------------------------------------------------------

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            return True, "Backend уже запущен."

        cmd, cwd = self._backend_command()

        if not Path(cmd[0]).exists():
            return False, f"Не найден backend: {cmd[0]}"

        self.clear_logs()
        self._append_log(f"[INFO] Запуск backend: {' '.join(cmd)}")
        self._append_log(f"[INFO] cwd: {cwd}")

        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            self.process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                universal_newlines=True,
                creationflags=creationflags,
            )

            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
            )
            self._reader_thread.start()

            online = self._wait_until_online(timeout=18.0)
            if online:
                self._append_log(f"[INFO] Backend доступен: http://{self.host}:{self.port}")
                return True, "Backend успешно запущен."

            pid = self.process.pid if self.process else "?"
            self._append_log(f"[ERROR] Backend не вышел в online. PID={pid}")
            return False, "Backend запустился, но не стал доступен по API."
        except Exception as e:
            self.process = None
            return False, f"Ошибка запуска backend: {e}"

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            self.process = None
            return True, "Backend уже остановлен."

        assert self.process is not None
        pid = self.process.pid
        self._append_log(f"[INFO] Остановка backend PID={pid}")

        try:
            if os.name == "nt":
                # Надёжно убивает и дочерние процессы uvicorn reload
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            else:
                self.process.send_signal(signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()

            self.process = None
            self._append_log("[INFO] Backend остановлен, порт освобождён.")
            return True, "Backend остановлен."
        except Exception as e:
            return False, f"Ошибка остановки backend: {e}"

    def restart(self) -> tuple[bool, str]:
        stop_ok, stop_msg = self.stop()
        if not stop_ok:
            return False, stop_msg

        time.sleep(1.0)
        return self.start()