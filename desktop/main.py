"""ADDGate desktop app: a native macOS window around the local ADDGate server.

Open the app -> the server starts in a background process -> the window shows the UI.
Quit (Cmd+Q or close the window) -> the server stops. If an ADDGate server is already running
(for example from ./start.sh), the window just uses it and leaves it running.

Run from source:  .venv/bin/python desktop/main.py
Build the app:    ./build_app.sh
"""
import json
import multiprocessing
import os
import pwd
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = int(os.environ.get("ADDGATE_PORT", 5055))
URL = f"http://127.0.0.1:{PORT}/"
HERE = Path(__file__).resolve().parent
if not getattr(sys, "frozen", False):  # running from source: make the backend importable
    sys.path.insert(0, str(HERE.parent / "backend"))


def login_shell():
    try:
        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/zsh"
    except KeyError:
        return "/bin/zsh"


def login_path():
    """Apps opened from Finder get a bare PATH (/usr/bin:/bin...), so `claude` wouldn't be found.
    Ask your login shell for the PATH you have in Terminal, plus the usual install spots."""
    found = ""
    try:
        out = subprocess.run([login_shell(), "-ilc", 'printf "\\n__ADDGATE_PATH__%s" "$PATH"'],
                             capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        marker = out.stdout.rsplit("__ADDGATE_PATH__", 1)
        found = marker[1].strip() if len(marker) == 2 else ""
    except Exception:
        pass
    home = Path.home()
    extra = [home / ".local/bin", home / ".claude/local", home / ".npm-global/bin", Path("/opt/homebrew/bin"),
             Path("/usr/local/bin"), Path("/usr/bin"), Path("/bin"), Path("/usr/sbin"), Path("/sbin")]
    parts = found.split(":") + os.environ.get("PATH", "").split(":") + [str(p) for p in extra]
    seen = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return ":".join(seen)


def port_open():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def is_addgate():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/auth/me", timeout=2) as r:
            return "has_users" in json.loads(r.read().decode())
    except Exception:
        return False


def watch_parent(parent_pid):
    """If the app itself disappears (crash, Force Quit), stop the server instead of leaving it
    running in the background holding port 5055."""
    import threading

    def loop():
        while os.getppid() == parent_pid:
            time.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)  # gunicorn's graceful shutdown

    threading.Thread(target=loop, daemon=True, name="parent-watch").start()


def run_server(parent_pid):
    """Runs in a child process: gunicorn needs its own main thread, and so does the window."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    watch_parent(parent_pid)
    from gunicorn.app.base import BaseApplication

    import app as addgate  # the Flask app (backend/app.py)

    class Server(BaseApplication):
        def load_config(self):
            # One worker on purpose: terminal tickets and sessions live in its memory.
            for k, v in {"bind": f"127.0.0.1:{PORT}", "workers": 1, "worker_class": "gthread", "threads": 32,
                         "timeout": 300, "graceful_timeout": 5, "loglevel": "warning"}.items():
                self.cfg.set(k, v)

        def load(self):
            return addgate.app

    Server().run()


def error_page(title, body):
    return f"""<html><body style="background:#0f1115;color:#e8e6e1;font:15px -apple-system,sans-serif;
      display:grid;place-items:center;height:100vh;margin:0"><div style="max-width:520px">
      <h2 style="margin:0 0 8px">{title}</h2><p style="color:#a3a8b3;line-height:1.5">{body}</p></div></body></html>"""


def main():
    multiprocessing.freeze_support()  # in the packaged app, this is where the server child starts
    multiprocessing.set_start_method("spawn", force=True)  # macOS default; same everywhere for testing
    os.environ["PATH"] = login_path()
    os.environ.setdefault("SHELL", login_shell())
    server = None
    problem = None

    if port_open():
        if not is_addgate():
            problem = ("Port 5055 is in use", "Something other than ADDGate is using port 5055. "
                       "Quit it (in Terminal: <code>lsof -ti :5055 | xargs kill</code>) and open ADDGate again.")
    else:
        server = multiprocessing.Process(target=run_server, args=(os.getpid(),), name="addgate-server")
        server.start()
        deadline = time.time() + 45
        while time.time() < deadline and not is_addgate():
            if not server.is_alive():
                break
            time.sleep(0.25)
        if not is_addgate():
            problem = ("ADDGate's server didn't start", "Open Terminal and run <code>cd ~/tools/ADDGate && ./start.sh</code> "
                       "to see the error, then paste it to Claude.")

    def stop(*_):
        raise SystemExit(0)

    # macOS sends SIGTERM on logout/restart and from Activity Monitor's Quit: clean up then too.
    signal.signal(signal.SIGTERM, stop)
    try:
        if os.environ.get("ADDGATE_NO_WINDOW"):  # headless mode, for testing the packaged server
            print("ADDGate server ready" if not problem else f"ADDGate problem: {problem[0]}", flush=True)
            while server is None or server.is_alive():
                time.sleep(1)
        else:
            import webview  # pywebview: a native macOS window (WebKit, like Safari)

            if problem:
                webview.create_window("ADDGate", html=error_page(*problem), width=640, height=360)
            else:
                webview.create_window("ADDGate", URL, width=1360, height=900, min_size=(900, 640),
                                      background_color="#0F1115", text_select=True)
            storage = Path.home() / "gate" / "desktop"
            storage.mkdir(parents=True, exist_ok=True)
            # private_mode=False keeps your sign-in cookie between launches (stored under ~/gate).
            webview.start(private_mode=False, storage_path=str(storage))
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if server and server.is_alive():  # quitting the app stops the server it started
            server.terminate()
            server.join(8)
            if server.is_alive():
                server.kill()


if __name__ == "__main__":
    main()
