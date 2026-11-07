"""A real shell in the browser, owner-only, behind several locks.

How a session opens:
  1. The owner has turned the terminal on in Settings (needs their password).
  2. They confirmed their password in the last 15 minutes ("sudo mode").
  3. The page asks POST /api/terminal/ticket (JSON-only, so other sites can't call it) and
     gets a random single-use ticket that expires in 30 seconds.
  4. It opens ws://localhost/ws/terminal?ticket=... The server checks the Host, the Origin,
     the session cookie, and that the ticket belongs to this same account, then spends it.
The shell runs as your Mac user, with ADDGate's own settings stripped from its environment."""
import codecs
import fcntl
import json
import os
import pty
import secrets
import select
import signal
import struct
import termios
import threading
import time

TICKET_TTL = 30            # seconds a ticket is valid
REAUTH_TTL = 15 * 60       # how long a password confirmation unlocks the terminal
IDLE_TIMEOUT = 30 * 60     # close a shell nobody has touched for this long
MAX_SESSIONS = 3           # per account
SCRUB_PREFIXES = ("ADDGATE_", "FLASK_", "WERKZEUG_")

_tickets = {}              # ticket -> {"uid", "expires"}
_sessions = {}             # session id -> Session
_lock = threading.Lock()


class TerminalError(Exception):
    pass


def issue_ticket(uid):
    now = time.time()
    with _lock:
        for t in [t for t, v in _tickets.items() if v["expires"] < now]:
            del _tickets[t]
        if sum(1 for s in _sessions.values() if s.uid == uid) >= MAX_SESSIONS:
            raise TerminalError(f"You already have {MAX_SESSIONS} terminals open. Close one first.")
        ticket = secrets.token_urlsafe(32)
        _tickets[ticket] = {"uid": uid, "expires": now + TICKET_TTL}
    return ticket


def redeem_ticket(ticket, uid):
    """Single use: the ticket is deleted whether or not it matches."""
    with _lock:
        rec = _tickets.pop(ticket or "", None)
    return bool(rec) and rec["uid"] == uid and rec["expires"] >= time.time()


def _shell_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith(SCRUB_PREFIXES)}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", ADDGATE_TERMINAL="1")
    return env


class Session:
    def __init__(self, uid):
        self.uid = uid
        self.id = secrets.token_hex(6)
        self.started = time.time()
        self.last_activity = time.time()
        self.closed = threading.Event()
        shell = os.environ.get("SHELL") or "/bin/zsh"
        if not os.path.exists(shell):
            shell = "/bin/bash"
        pid, fd = pty.fork()
        if pid == 0:  # child: become the shell
            try:
                os.chdir(os.path.expanduser("~"))
                os.execvpe(shell, [shell, "-l"], _shell_env())
            finally:
                os._exit(127)
        self.pid, self.fd = pid, fd

    def resize(self, cols, rows):
        cols, rows = max(10, min(int(cols), 500)), max(4, min(int(rows), 200))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def write(self, data):
        self.last_activity = time.time()
        os.write(self.fd, data.encode("utf-8", errors="replace"))

    def close(self, reason="closed"):
        if self.closed.is_set():
            return
        self.closed.set()
        self.close_reason = reason
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            time.sleep(0.2)
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def close_all(uid, reason):
    with _lock:
        mine = [s for s in _sessions.values() if s.uid == uid]
    for s in mine:
        s.close(reason)


def count(uid):
    with _lock:
        return sum(1 for s in _sessions.values() if s.uid == uid)


def run(ws, uid, audit):
    """Pump bytes between the WebSocket and the shell until either side ends."""
    with _lock:
        if sum(1 for s in _sessions.values() if s.uid == uid) >= MAX_SESSIONS:
            ws.close(reason=1008, message="Too many terminals open")
            return
        sess = Session(uid)
        _sessions[sess.id] = sess
    audit(uid, "terminal_open", f"session {sess.id}")
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def pump_output():
        try:
            while not sess.closed.is_set():
                ready, _, _ = select.select([sess.fd], [], [], 0.5)
                if not ready:
                    continue
                try:
                    chunk = os.read(sess.fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                sess.last_activity = time.time()
                ws.send(decoder.decode(chunk).replace(CONTROL, ""))
        except Exception:
            pass
        sess.close(getattr(sess, "close_reason", "shell exited"))

    reader = threading.Thread(target=pump_output, daemon=True)
    reader.start()
    try:
        while not sess.closed.is_set():
            if time.time() - sess.last_activity > IDLE_TIMEOUT:
                sess.close("idle timeout")
                try:
                    ws.send("\r\n\x1b[33m[ADDGate closed this terminal after 30 idle minutes]\x1b[0m\r\n")
                except Exception:
                    pass
                break
            msg = ws.receive(timeout=1)
            if msg is None:
                continue
            try:
                m = json.loads(msg)
            except (TypeError, ValueError):
                continue
            if m.get("type") == "input" and isinstance(m.get("data"), str):
                sess.write(m["data"][:65536])
            elif m.get("type") == "resize":
                sess.resize(m.get("cols", 80), m.get("rows", 24))
    except Exception:
        pass  # browser went away
    finally:
        sess.close(getattr(sess, "close_reason", "browser closed"))
        with _lock:
            _sessions.pop(sess.id, None)
        audit(uid, "terminal_close", f"session {sess.id}, {int(time.time() - sess.started)}s, {sess.close_reason}")
        _hang_up(ws, sess.close_reason)


CONTROL = "\x00"  # messages starting with NUL are control messages, never terminal output


def _hang_up(ws, reason):
    """Ask the browser to close the socket itself, then wait briefly for it. Closing from the
    server side makes the dev server write stray bytes the browser reports as a bad frame."""
    try:
        ws.send(CONTROL + json.dumps({"type": "exit", "reason": reason}))
        end = time.time() + 3
        while time.time() < end:
            ws.receive(timeout=0.5)
    except Exception:
        return  # the browser closed: the clean path
    try:
        ws.close()
    except Exception:
        pass
