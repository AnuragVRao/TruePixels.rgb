"""Seed a SCRATCH database for run_admin_flows.py (Phase 5b). Never the dev DB.

    DATABASE_URL=<scratch> python frontend/e2e/seed_admin_scratch.py <out_json>

Creates two admins, one normal user, 25 filler users (so the users screen has
two pages) and one D6 row whose detail is an HTML/script payload (the XSS
check). Passwords are generated per run and written only to <out_json>.
Refuses any database the test guard does not accept as scratch.
"""
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.m1_access.models import User  # noqa: E402
from app.m1_access.security import hash_password  # noqa: E402
from app.m3_results.models import LogEntry  # noqa: E402
from app.shared.db import SessionLocal, engine, refuse_unless_scratch  # noqa: E402

XSS = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>'

refuse_unless_scratch(engine.url)
stamp = int(time.time())
password = "Adm-" + secrets.token_urlsafe(12) + "9a"
people = {
    "admin": (f"admin{stamp}@example.com", "Admin"),
    "admin2": (f"admin2-{stamp}@example.com", "Admin"),
    "user": (f"plain{stamp}@example.com", "User"),
}
db = SessionLocal()
try:
    ids = {}
    for key, (email, role) in people.items():
        user = User(full_name=f"E2E {key}", email=email, password_hash=hash_password(password), role=role,
                    account_status="active", is_email_verified=True)
        db.add(user)
        db.flush()
        ids[key] = user.user_id
    for n in range(25):
        db.add(User(full_name=f"Filler {n}", email=f"filler{n}-{stamp}@example.com",
                    password_hash=hash_password(password), role="User", account_status="active",
                    is_email_verified=True))
    db.add(LogEntry(event_type="error", severity="error", event_detail=f"e2e payload {stamp}: {XSS}"))
    db.commit()
finally:
    db.close()
Path(sys.argv[1]).write_text(json.dumps({
    "password": password, "stamp": stamp, "xss": XSS,
    **{key: {"email": email, "id": ids[key]} for key, (email, _) in people.items()},
}))
print("seeded", {k: v for k, v in ids.items()})
