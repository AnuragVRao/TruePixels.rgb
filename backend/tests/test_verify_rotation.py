"""verify_rotation.py never prints a secret - old or new, whatever goes wrong.

Runs the real script on throwaway .env files full of sentinel values,
including a malformed URL and missing keys, and checks stdout + stderr.
The database URLs point at a port nothing listens on; the API at another.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_rotation.py"
SENTINELS = {
    "old_pw": "OLDPWsentinel4f1c", "new_pw": "NEWPWsentinel9a2b",
    "old_jwt": "OLDJWTsentinel" + "a" * 60, "new_jwt": "NEWJWTsentinel" + "b" * 60,
}


def _env(path: Path, pw: str, jwt: str, url: str | None) -> Path:
    lines = [f"POSTGRES_USER=sentineluser", f"POSTGRES_PASSWORD={pw}", "POSTGRES_DB=sentineldb",
             f"JWT_SECRET_KEY={jwt}"]
    if url is not None:
        lines.append(f"DATABASE_URL={url}")
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize("variant", ["unreachable", "malformed", "missing-url"])
def test_output_never_contains_old_or_new_values(tmp_path, variant):
    s = SENTINELS
    old_url = f"postgresql+psycopg://sentineluser:{s['old_pw']}@127.0.0.1:1/sentineldb"
    new_url = {"unreachable": f"postgresql+psycopg://sentineluser:{s['new_pw']}@127.0.0.1:1/sentineldb",
               "malformed": f"not a url :// {s['new_pw']} @@",
               "missing-url": None}[variant]
    old = _env(tmp_path / "old.env", s["old_pw"], s["old_jwt"], old_url)
    new = _env(tmp_path / "new.env", s["new_pw"], s["new_jwt"], new_url)
    result = subprocess.run([sys.executable, str(SCRIPT), "--old", str(old), "--new", str(new),
                             "--api", "http://127.0.0.1:1"], capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    for value in SENTINELS.values():
        assert value not in output, f"{variant}: a secret value was printed"
    assert "sentineluser" not in output  # nor any part of a URL
    assert result.returncode != 0       # nothing here can pass
    for line in result.stdout.splitlines():
        assert line.endswith((": True", ": False")) or line.startswith("verify_rotation: could not run"), line
