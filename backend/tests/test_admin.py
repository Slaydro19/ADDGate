"""Admin role end to end, against a throwaway ADDGATE_HOME (never touches ~/gate).

Run:  cd backend && ../.venv/bin/python -m unittest tests.test_admin -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="addgate-test-")
os.environ["ADDGATE_HOME"] = HOME
os.environ["ADDGATE_CLAUDE_BIN"] = "/nonexistent-claude"   # no real Claude calls
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as addgate  # noqa: E402
import claude_client as cc  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import security  # noqa: E402

PW = "correct-horse-1"


def client():
    return addgate.app.test_client()


def post(c, path, data=None, method="post"):
    return getattr(c, method)(path, json=data or {}, headers={"Host": "localhost"})


def get(c, path):
    return c.get(path, headers={"Host": "localhost"})


class AdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alice = client()                      # first account: owner and admin
        r = post(cls.alice, "/api/auth/signup", {"username": "alice", "password": PW})
        cls.alice_id = r.get_json()["user"]["id"]
        cls.bob = client()
        r = post(cls.bob, "/api/auth/signup", {"username": "bob", "password": PW})
        cls.bob_id = r.get_json()["user"]["id"]

    def confirm(self, c, pw=PW):
        self.assertEqual(post(c, "/api/auth/confirm", {"password": pw}).status_code, 200)

    # --- roles ---
    def test_01_first_account_is_admin_second_is_not(self):
        me = get(self.alice, "/api/auth/me").get_json()["user"]
        self.assertTrue(me["is_admin"] and me["is_owner"])
        me = get(self.bob, "/api/auth/me").get_json()["user"]
        self.assertFalse(me["is_admin"])

    def test_02_non_admin_is_refused_everywhere(self):
        for path in ("/api/admin/overview", "/api/admin/backups", "/api/admin/health", "/api/admin/audit", "/api/admin/settings"):
            self.assertEqual(get(self.bob, path).status_code, 403, path)
        self.assertEqual(post(self.bob, f"/api/admin/users/{self.alice_id}/disabled", {"disabled": True}).status_code, 403)
        self.assertEqual(post(self.bob, "/api/admin/users", {"username": "evil"}).status_code, 403)

    def test_03_overview_has_counts_not_content(self):
        data = get(self.alice, "/api/admin/overview").get_json()
        names = {u["username"] for u in data["users"]}
        self.assertTrue({"alice", "bob"} <= names)
        row = data["users"][0]
        for private in ("answer", "answers", "question", "transcript", "commands", "password_hash"):
            self.assertNotIn(private, row)
        self.assertIn("concepts", row)

    def test_04_users_can_not_set_their_own_cap(self):
        post(self.bob, "/api/config", {"account_token_cap": 5}, method="put")
        self.assertEqual(get(self.bob, "/api/config").get_json()["account_token_cap"], 0)

    # --- temp password flow ---
    def test_05_created_account_must_change_password(self):
        r = post(self.alice, "/api/admin/users", {"username": "carol", "display_name": "Carol"}).get_json()
        temp, cid = r["temp_password"], r["user"]["id"]
        self.assertTrue(r["user"]["must_change_password"])
        c = client()
        self.assertEqual(post(c, "/api/auth/login", {"username": "carol", "password": temp}).status_code, 200)
        self.assertEqual(get(c, "/api/vault").status_code, 403)                     # blocked until changed
        self.assertEqual(get(c, "/api/vault").get_json()["kind"], "must_change")
        r = post(c, "/api/auth/password", {"current": temp, "new": "carols-own-pass"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(get(c, "/api/vault").status_code, 200)
        self.assertFalse(get(c, "/api/auth/me").get_json()["user"]["must_change_password"])
        self.carol_id = cid

    def test_06_reset_password_needs_reauth_and_signs_out(self):
        c = client()
        r = post(self.alice, "/api/admin/users", {"username": "dave", "password": "daves-password"}).get_json()
        did = r["user"]["id"]
        post(c, "/api/auth/login", {"username": "dave", "password": "daves-password"})
        post(c, "/api/auth/password", {"current": "daves-password", "new": "daves-new-pass"})
        self.assertEqual(get(c, "/api/vault").status_code, 200)
        client_a = self.alice
        post(client_a, "/api/auth/confirm", {"password": "wrong"})                  # a wrong confirm gives nothing
        a2 = client()
        post(a2, "/api/auth/login", {"username": "alice", "password": PW})
        resp = post(a2, f"/api/admin/users/{did}/reset-password")
        self.assertEqual(resp.get_json()["kind"], "reauth")
        self.confirm(a2)
        resp = post(a2, f"/api/admin/users/{did}/reset-password")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()["temp_password"]), 14)
        self.assertEqual(get(c, "/api/vault").status_code, 401)                     # old session is dead

    # --- guards ---
    def test_07_last_admin_is_protected(self):
        a = self.alice
        self.confirm(a)
        r = post(a, f"/api/admin/users/{self.alice_id}/role", {"is_admin": False})
        self.assertEqual((r.status_code, r.get_json()["kind"]), (409, "guard"))
        r = post(a, f"/api/admin/users/{self.alice_id}/disabled", {"disabled": True})
        self.assertEqual(r.status_code, 409)
        r = post(a, f"/api/admin/users/{self.alice_id}", {"confirm": "alice"}, method="delete")
        self.assertEqual(r.status_code, 409)

    def test_08_promote_then_demote_original(self):
        a = self.alice
        self.confirm(a)
        self.assertEqual(post(a, f"/api/admin/users/{self.bob_id}/role", {"is_admin": True}).status_code, 200)
        self.assertTrue(get(self.bob, "/api/auth/me").get_json()["user"]["is_admin"])
        self.assertEqual(get(self.bob, "/api/admin/overview").status_code, 200)
        # with bob an admin, alice may step down; then put things back
        self.assertEqual(post(a, f"/api/admin/users/{self.alice_id}/role", {"is_admin": False}).status_code, 200)
        self.assertEqual(get(a, "/api/admin/overview").status_code, 403)
        self.confirm(self.bob)
        self.assertEqual(post(self.bob, f"/api/admin/users/{self.alice_id}/role", {"is_admin": True}).status_code, 200)
        self.assertEqual(post(self.bob, f"/api/admin/users/{self.bob_id}/role", {"is_admin": False}).status_code, 200)

    # --- disable, lock, sign out ---
    def test_09_disable_blocks_login_and_session(self):
        r = post(self.alice, "/api/admin/users", {"username": "erin", "password": "erins-password"}).get_json()
        eid = r["user"]["id"]
        c = client()
        post(c, "/api/auth/login", {"username": "erin", "password": "erins-password"})
        post(c, "/api/auth/password", {"current": "erins-password", "new": "erins-new-pass"})
        self.assertEqual(post(self.alice, f"/api/admin/users/{eid}/disabled", {"disabled": True}).status_code, 200)
        self.assertEqual(get(c, "/api/vault").status_code, 401)
        resp = post(client(), "/api/auth/login", {"username": "erin", "password": "erins-new-pass"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("turned off", resp.get_json()["error"])
        resp = post(client(), "/api/auth/login", {"username": "erin", "password": "wrong-password"})
        self.assertNotIn("turned off", resp.get_json()["error"])                    # can't probe usernames
        self.assertEqual(post(self.alice, f"/api/admin/users/{eid}/disabled", {"disabled": False}).status_code, 200)
        self.assertEqual(post(client(), "/api/auth/login", {"username": "erin", "password": "erins-new-pass"}).status_code, 200)

    def test_10_cannot_disable_self(self):
        r = post(self.alice, f"/api/admin/users/{self.alice_id}/disabled", {"disabled": True})
        self.assertEqual(r.status_code, 409)

    def test_11_unlock_clears_lockout(self):
        for _ in range(5):
            security.login_failed("bob")
        self.assertTrue(security.login_blocked("bob"))
        users_ = get(self.alice, "/api/admin/overview").get_json()["users"]
        self.assertTrue(next(u for u in users_ if u["username"] == "bob")["locked"])
        self.assertEqual(post(self.alice, f"/api/admin/users/{self.bob_id}/unlock").status_code, 200)
        self.assertFalse(security.login_blocked("bob"))

    def test_12_force_sign_out(self):
        c = client()
        post(c, "/api/auth/login", {"username": "bob", "password": PW})
        self.assertEqual(get(c, "/api/vault").status_code, 200)
        self.assertEqual(post(self.alice, f"/api/admin/users/{self.bob_id}/signout").status_code, 200)
        self.assertEqual(get(c, "/api/vault").status_code, 401)
        post(self.bob, "/api/auth/login", {"username": "bob", "password": PW})     # sign bob back in for later tests

    # --- sign-up policy ---
    def test_13_signup_policy(self):
        self.assertTrue(get(client(), "/api/auth/me").get_json()["signup_open"])
        r = post(self.alice, "/api/admin/settings", {"signup_mode": "admin_only"}, method="put")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(get(client(), "/api/auth/me").get_json()["signup_open"])
        r = post(client(), "/api/auth/signup", {"username": "mallory", "password": PW})
        self.assertEqual(r.status_code, 403)
        post(self.alice, "/api/admin/settings", {"signup_mode": "open"}, method="put")
        self.assertEqual(post(client(), "/api/auth/signup", {"username": "frank", "password": PW}).status_code, 200)
        self.assertEqual(post(self.alice, "/api/admin/settings", {"signup_mode": "nope"}, method="put").status_code, 400)

    def test_14_new_account_defaults_applied(self):
        post(self.alice, "/api/admin/settings", {"new_account": {"questions_per_close": 3, "hint_delay_seconds": 15}}, method="put")
        c = client()
        post(c, "/api/auth/signup", {"username": "gina", "password": PW})
        cfg = get(c, "/api/config").get_json()
        self.assertEqual((cfg["questions_per_close"], cfg["hint_delay_seconds"]), (3, 15))
        post(self.alice, "/api/admin/settings", {"new_account": {"questions_per_close": 5, "hint_delay_seconds": 60}}, method="put")

    # --- token cap ---
    def test_15_account_cap_stops_claude_calls(self):
        r = post(self.alice, f"/api/admin/users/{self.bob_id}/cap", {"cap": 1000})
        self.assertEqual(r.get_json()["cap"], 1000)
        from datetime import date
        with db.write() as c:
            c.execute("INSERT INTO usage_user (user_id, day, work_tokens, calls) VALUES (?, ?, 1000, 1) "
                      "ON CONFLICT(user_id, day) DO UPDATE SET work_tokens = 1000", (self.bob_id, date.today().isoformat()))
        config.use_user(self.bob_id)
        try:
            with self.assertRaises(cc.ClaudeError) as ctx:
                cc.ask("hi")
            self.assertEqual(ctx.exception.kind, "cap")
        finally:
            config.use_user(None)
        post(self.alice, f"/api/admin/users/{self.bob_id}/cap", {"cap": 0})
        self.assertEqual(post(self.alice, f"/api/admin/users/{self.bob_id}/cap", {"cap": "lots"}).status_code, 400)

    # --- delete + backups ---
    def test_16_delete_needs_reauth_and_typed_name_and_backs_up(self):
        r = post(self.alice, "/api/admin/users", {"username": "hank", "password": "hanks-password"}).get_json()
        hid = r["user"]["id"]
        a = self.alice
        # reauth window may still be open from earlier tests; force it closed to prove the check
        with a.session_transaction() as s:
            s["reauth_at"] = 0
        self.assertEqual(post(a, f"/api/admin/users/{hid}", {"confirm": "hank"}, method="delete").get_json()["kind"], "reauth")
        self.confirm(a)
        self.assertEqual(post(a, f"/api/admin/users/{hid}", {"confirm": "nope"}, method="delete").status_code, 400)
        r = post(a, f"/api/admin/users/{hid}", {"confirm": "HANK"}, method="delete")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(db.one("SELECT 1 AS x FROM users WHERE id = ?", (hid,)))
        names = [b["name"] for b in get(a, "/api/admin/backups").get_json()["backups"]]
        self.assertIn(r.get_json()["backup"], names)

    def test_17_backup_and_restore(self):
        a = self.alice
        made = post(a, "/api/admin/backups").get_json()["backup"]
        post(a, "/api/admin/users", {"username": "ivy", "password": "ivys-password-1"})
        self.assertIsNotNone(users_by_name("ivy"))
        self.confirm(a)
        self.assertEqual(post(a, f"/api/admin/backups/{made['name']}/restore", {"confirm": "no"}).status_code, 400)
        for evil in ("../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "x.db/../../y.db"):   # never reaches a file outside backups/
            self.assertIn(post(a, f"/api/admin/backups/{evil}/restore", {"confirm": "RESTORE"}).status_code, (404, 405), evil)
        self.assertEqual(post(a, "/api/admin/backups/not-a-backup.db/restore", {"confirm": "RESTORE"}).status_code, 404)
        r = post(a, f"/api/admin/backups/{made['name']}/restore", {"confirm": "RESTORE"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIsNone(users_by_name("ivy"))                                     # rolled back
        self.assertIsNotNone(users_by_name("alice"))
        kinds = {b["kind"] for b in get(a, "/api/admin/backups").get_json()["backups"]}
        self.assertIn("pre-restore", kinds)

    def test_18_health_and_audit(self):
        h = get(self.alice, "/api/admin/health").get_json()
        for key in ("version", "claude", "hook", "database", "accounts", "backups"):
            self.assertIn(key, h)
        events = get(self.alice, "/api/admin/audit?limit=200").get_json()["events"]
        seen = {e["event"] for e in events}
        for want in ("login", "password_reset", "account_deleted", "admin_made", "account_disabled"):
            self.assertIn(want, seen)

    def test_19_cli_recovery(self):
        import users
        users.set_admin_cli("frank", True)
        self.assertTrue(users.find("frank")["is_admin"])
        users.set_admin_cli("frank", False)


def users_by_name(name):
    return db.one("SELECT * FROM users WHERE username = ?", (name,))


if __name__ == "__main__":
    unittest.main()
