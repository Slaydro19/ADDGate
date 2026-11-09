"""Admin commands for ADDGate (run from the backend folder with the venv's Python).

  ../.venv/bin/python manage.py users                    list accounts
  ../.venv/bin/python manage.py reset-password <name>    set a new password (no email on a local app)
  ../.venv/bin/python manage.py backup                   copy the database to ~/gate/backups/
  ../.venv/bin/python manage.py make-admin <name>        give an account the admin role (recovery if no admin is left)
  ../.venv/bin/python manage.py remove-admin <name>      take the admin role away
"""
import getpass
import sqlite3
import sys
from datetime import datetime

import db
import users
from config import GATE_HOME, ensure_dirs


def main(argv):
    ensure_dirs()
    db.init()
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "users":
        for u in db.all_rows("SELECT username, display_name, created, is_admin, disabled FROM users ORDER BY created"):
            flags = ("admin " if u["is_admin"] else "") + ("off" if u["disabled"] else "")
            print(f"{u['username']:<24} {u['display_name']:<24} since {u['created'][:10]}  {flags}")
    elif cmd == "reset-password" and len(argv) > 2:
        pw = getpass.getpass(f"New password for {argv[2]}: ")
        if pw != getpass.getpass("Again: "):
            sys.exit("Passwords don't match.")
        try:
            users.reset_password(argv[2], pw)
        except users.AuthError as e:
            sys.exit(str(e))
        print("Password reset.")
    elif cmd in ("make-admin", "remove-admin") and len(argv) > 2:
        try:
            users.set_admin_cli(argv[2], cmd == "make-admin")
        except users.AuthError as e:
            sys.exit(str(e))
        print(f"{argv[2]} is {'now' if cmd == 'make-admin' else 'no longer'} an admin.")
    elif cmd == "backup":
        dest_dir = GATE_HOME / "backups"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / f"addgate-{datetime.now():%Y%m%d-%H%M%S}.db"
        with sqlite3.connect(dest) as out:
            db.connect().backup(out)  # consistent copy even while ADDGate is running
        dest.chmod(0o600)
        print(f"Backed up to {dest}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
