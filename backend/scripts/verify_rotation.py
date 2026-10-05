"""Verify a secret rotation (docs/rotate-secrets.md step d). Prints ONLY True/False.

    cd backend
    python scripts/verify_rotation.py [--old .env.before-rotation] [--api http://127.0.0.1:8000]

Never prints a value, a URL or an exception message (those can contain
credentials). Each line is "<check>: True|False"; the exit code is 0 only if
every check is True. The API checks need the server running with the NEW .env.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _connects(url: str) -> bool:
    from sqlalchemy import create_engine

    engine = None
    try:  # create_engine itself can raise with the URL in its message
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        engine.connect().close()
        return True
    except Exception:  # noqa: BLE001 - the message may contain the URL; never shown
        return False
    finally:
        if engine is not None:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default=str(BACKEND / ".env.before-rotation"))
    parser.add_argument("--new", default=str(BACKEND / ".env"))
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    from dotenv import dotenv_values

    new = dotenv_values(args.new)
    old = dotenv_values(args.old)
    checks: dict[str, bool] = {}

    checks["old database password rejected"] = (
        old.get("POSTGRES_PASSWORD") != new.get("POSTGRES_PASSWORD") and not _connects(old["DATABASE_URL"]))
    checks["new database password accepted"] = _connects(new["DATABASE_URL"])
    checks["DATABASE_URL carries the new password"] = (
        bool(new.get("POSTGRES_PASSWORD")) and f":{new['POSTGRES_PASSWORD']}@" in new.get("DATABASE_URL", ""))
    checks["JWT key changed and long"] = (
        old.get("JWT_SECRET_KEY") != new.get("JWT_SECRET_KEY") and len(new.get("JWT_SECRET_KEY") or "") >= 64)
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET_KEY"):
        checks[f"{key} is hex/URL-safe (no / + = quotes)"] = not any(
            ch in (new.get(key) or "/") for ch in "/+='\"")

    # Container environment: only POSTGRES_*, never the JWT key or DATABASE_URL.
    try:
        cid = subprocess.run(["docker", "compose", "--env-file", args.new, "ps", "-q", "db"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        env = subprocess.run(["docker", "inspect", cid, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        names = {line.split("=", 1)[0] for line in env}
        del env
        checks["container env has no JWT_SECRET_KEY / DATABASE_URL"] = bool(cid) and not (
            {"JWT_SECRET_KEY", "DATABASE_URL"} & names)
    except Exception:  # noqa: BLE001
        checks["container env has no JWT_SECRET_KEY / DATABASE_URL"] = False

    # API: a token signed with the OLD key must be refused.
    try:
        import httpx
        from jose import jwt

        now = int(time.time())
        claims = {"sub": "1", "email": "rotation-check@example.com", "role": "Admin",
                  "account_status": "active", "iat": now, "exp": now + 600}
        stale = jwt.encode(claims, old["JWT_SECRET_KEY"], algorithm="HS256")
        r = httpx.get(f"{args.api}/api/v1/auth/me", headers={"Authorization": f"Bearer {stale}"}, timeout=10)
        checks["token signed with the OLD key rejected (401)"] = r.status_code == 401
        checks["API ready"] = httpx.get(f"{args.api}/ready", timeout=10).status_code == 200
    except Exception:  # noqa: BLE001
        checks["token signed with the OLD key rejected (401)"] = False
        checks["API ready"] = False

    for name, ok in checks.items():
        print(f"{name}: {ok}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND))
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - never a traceback: it could quote a value
        print(f"verify_rotation: could not run ({type(exc).__name__}); no value shown")
        raise SystemExit(2)
