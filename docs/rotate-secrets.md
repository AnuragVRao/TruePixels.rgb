# Rotating the database password and the JWT signing key

Run every step in **PowerShell** from the repository root, in this order.
**Nothing here prints a secret.** New values go from a variable straight
into `backend/.env` or the database. Checks print only `True`/`False` (or
file names).

- **New values:** `secrets.token_hex(32)` gives 64 hex characters (`0-9a-f`):
  no `/`, `+`, `=` or quotes. That makes it safe inside `DATABASE_URL` and
  inside SQL quotes, and it needs no URL-encoding.
- **Writing `.env`:** use `[IO.File]::WriteAllLines`, which writes UTF-8
  without a BOM. `Set-Content -Encoding utf8` in Windows PowerShell 5.1
  adds a BOM, and a BOM breaks the first key.
- **Compose:** every `docker compose` command takes `--env-file backend/.env`.
  The compose file refuses to run without it.

## Where the old database password lives

A scan on 2026-10-05 (file names only) found it in exactly one file:
`backend/.env`.

It is **not** in:
- git history;
- the repository;
- `pgpass`;
- the PowerShell history;
- any committed script.

`TEST_DATABASE_URL` is never stored. The test commands build it from `.env`
at run time (section e).

Outside files, the old value also lives in:
- the **running database container's environment**, replaced in step (c);
- the database's own role password, replaced in step (b).

If you keep the URL anywhere else (an IDE run configuration, a shell
profile), the scan in step (d6) finds it by name.

## (0) Prepare

1. Stop the API (uvicorn) and the Vite dev server.
2. Make sure the database is running, and back up `.env`. The backup is
   gitignored (`.env.*`) and is needed only for step (d); delete it at the
   end.

   ```powershell
   docker compose --env-file backend/.env up -d db
   Copy-Item backend\.env backend\.env.before-rotation
   ```

## (a) Compose: the container gets only `POSTGRES_*` (already done in the repo)

`compose.yaml` no longer uses `env_file: backend/.env`. That setting handed
the container every key, `JWT_SECRET_KEY` included. The container now
receives only `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`.

**Do not recreate the container yet.** The running container still has the
old environment until step (c).

## (b) Rotate both secrets

```powershell
# --- database password: change it in PostgreSQL (SQL on stdin, not the command line) ---
$db = python -c "import secrets; print(secrets.token_hex(32))"
"ALTER USER truepixels WITH PASSWORD '$db';" | docker compose --env-file backend/.env exec -T db psql -U truepixels -d postgres -v ON_ERROR_STOP=1 -q

# --- JWT signing key ---
$jwt = python -c "import secrets; print(secrets.token_hex(48))"

# --- write both into backend/.env: POSTGRES_PASSWORD, the password inside
#     DATABASE_URL (and inside TEST_DATABASE_URL if you added one), JWT_SECRET_KEY ---
$lines = Get-Content backend\.env | ForEach-Object {
  if     ($_ -match '^POSTGRES_PASSWORD=')                                  { "POSTGRES_PASSWORD=$db" }
  elseif ($_ -match '^((?:TEST_)?DATABASE_URL=[^:]+://[^:]+:)[^@]*(@.*)$')  { $Matches[1] + $db + $Matches[2] }
  elseif ($_ -match '^JWT_SECRET_KEY=')                                     { "JWT_SECRET_KEY=$jwt" }
  else   { $_ }
}
[IO.File]::WriteAllLines((Resolve-Path backend\.env), [string[]]$lines)
Remove-Variable db, jwt, lines
```

Inside the container, `psql` uses the local socket, which the `postgres`
image trusts, so the old password is not needed for the `ALTER USER`.

The scratch databases (`truepixels_test`, and any recreated
`*_regression`) belong to the same user. They follow automatically.

## (c) Recreate the database container, once

This keeps the data volume. **Never** use `down -v`, which deletes all data.

```powershell
docker compose --env-file backend/.env up -d --force-recreate db
docker compose --env-file backend/.env ps db   # wait until it is (healthy)
```

## (d) Verify: every check must print True

1. Start the API with the new `.env` (`cd backend; python -m uvicorn app.main:app`)
   and wait until `GET /ready` returns 200.
2. In a second terminal:

```powershell
cd backend
python scripts/verify_rotation.py      # compares .env with .env.before-rotation; prints only True/False
cd ..
```

The script prints a single True/False line for each of the checks below.
It never prints a value, a URL or an exception message, and its exit code
is 0 only if every line is True.

| Check | What it tests |
|---|---|
| old database password rejected | connects with the backup's `DATABASE_URL` and expects a failure |
| new database password accepted | connects with the current `DATABASE_URL` |
| `DATABASE_URL` carries the new password | the URL in `.env` was updated as well |
| JWT key changed and long | the key differs from the backup and is long |
| both values are hex/URL-safe | no `/`, `+`, `=` or quotes |
| container env has no `JWT_SECRET_KEY` / `DATABASE_URL` | reads `docker inspect` and compares variable **names** only |
| token signed with the OLD key rejected (401) | asks the running API to accept a token signed with the old key |
| API ready | `/ready` returns 200 |

A dry run before rotating, on 2026-10-05, printed **False** for "container
env has no JWT_SECRET_KEY": today's container still has the key, as
expected until step (c).

Then:

- **Old password elsewhere:** prints file names only; no output means it is
  nowhere else.

  ```powershell
  $old = (Select-String -Path backend\.env.before-rotation -Pattern '^POSTGRES_PASSWORD=(.*)$').Matches[0].Groups[1].Value
  Get-ChildItem -Recurse -File -Path . -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\(node_modules|\.git|\.venv|datasets|storage)\\' -and $_.Name -ne '.env.before-rotation' -and $_.Length -lt 50MB } |
    Select-String -SimpleMatch -Pattern $old -List | ForEach-Object { $_.Path }
  Remove-Variable old
  ```

  If you ever saved the URL in an IDE run configuration or a shell profile,
  run the same `Select-String` over that file.
- **Fresh sign-in:** sign in in the browser. Tabs that were signed in
  before go back to the sign-in page, because the old token now gets a 401.
- **Test suites:** both must pass (section e).

## (e) Test suites with the new password, never typed out

```powershell
python -m pytest backend/tests -q                                    # SQLite
$u = (Select-String -Path backend\.env -Pattern '^DATABASE_URL=(.*)/[^/]*$').Matches[0].Groups[1].Value
$env:TEST_DATABASE_URL = "$u/truepixels_test"; python -m pytest backend/tests -q; Remove-Item Env:TEST_DATABASE_URL
Remove-Variable u
```

## (f) Clean up, only after (d) printed True on every line

`verify_rotation.py` needs the backup: it is how the script proves the OLD
values are dead. Delete the backup only after a full True run. The script
never prints a value, old or new: whatever fails, it prints True/False, or
"could not run (<error type>)" (tested with sentinel values,
`backend/tests/test_verify_rotation.py`).


```powershell
Remove-Item backend\.env.before-rotation   # it still holds the old values
```

## Notes

- After these steps both old values are dead:
  - the old database password no longer authenticates;
  - old tokens no longer verify, and they would have expired within
    8 hours anyway (`SESSION_EXPIRE_HOURS`).
- **This conversation's transcript** still contains the old database
  password (from 2026-10-03). Rotating makes it useless; it cannot be
  erased from the transcript.
- If either value leaks again, repeat (0), (b), (d) and (f). Step (c) is
  needed only after a compose change.
