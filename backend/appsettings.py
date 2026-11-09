"""Machine-wide settings an admin controls (stored in the app_settings table)."""
import db

DEFAULTS = {
    "signup_mode": "open",   # "open": anyone at this Mac can create an account; "admin_only": admins create them
    # applied to every new account's own settings when it is created
    "new_account": {"questions_per_close": 5, "hint_delay_seconds": 60, "daily_token_limit": 0, "account_token_cap": 0},
}
SIGNUP_MODES = ("open", "admin_only")
LIMITS = {"questions_per_close": (1, 10), "hint_delay_seconds": (0, 3600),
          "daily_token_limit": (0, 100_000_000), "account_token_cap": (0, 100_000_000)}


def get():
    out = {"signup_mode": DEFAULTS["signup_mode"], "new_account": dict(DEFAULTS["new_account"])}
    for row in db.all_rows("SELECT key, value FROM app_settings"):
        val = db.loads(row["value"])
        if row["key"] == "signup_mode" and val in SIGNUP_MODES:
            out["signup_mode"] = val
        elif row["key"] == "new_account" and isinstance(val, dict):
            out["new_account"].update({k: v for k, v in val.items() if k in LIMITS})
    return out


def _put(key, value):
    with db.write() as c:
        c.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, db.dumps(value)))


def update(signup_mode=None, new_account=None):
    if signup_mode is not None:
        if signup_mode not in SIGNUP_MODES:
            raise ValueError("Sign-up must be open or admin-only.")
        _put("signup_mode", signup_mode)
    if new_account is not None:
        clean = {}
        for k, (lo, hi) in LIMITS.items():
            if k in new_account:
                try:
                    n = int(new_account[k])
                except (TypeError, ValueError):
                    raise ValueError(f"{k.replace('_', ' ')} must be a number.")
                clean[k] = max(lo, min(hi, n))
        merged = get()["new_account"]
        merged.update(clean)
        _put("new_account", merged)
    return get()


def signup_open():
    return get()["signup_mode"] == "open"


def apply_new_account_defaults(user_id):
    """Give a new account the admin's defaults (only the ones that differ from the built-ins)."""
    import config
    d = get()["new_account"]
    cfg = {k: v for k, v in d.items() if v != config.DEFAULT_CONFIG.get(k)}
    if cfg:
        with db.write() as c:
            c.execute("INSERT INTO user_config (user_id, data) VALUES (?, ?) "
                      "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data", (user_id, db.dumps(cfg)))
