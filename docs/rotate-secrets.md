# Rotating the database password and the JWT signing key

These steps never print a secret. Run them in **PowerShell** from the
repository root. New values go from a variable straight into the files and
the database; nothing is echoed, and nothing goes into shell history as a
literal value.

`backend/.env` is rewritten with `[IO.File]::WriteAllLines`, which writes
UTF-8 **without** a BOM. (`Set-Content -Encoding utf8` in Windows PowerShell
5.1 adds a BOM, and a BOM in front of the first key breaks that key.)

## 0. Before you start

1. Stop the API (uvicorn) and the Vite dev server.
2. Make sure the database container is running:

   ```powershell
   docker compose up -d db
   ```

3. Back up `.env` locally. The backup is gitignored like the original; delete
   it once you are done.

   ```powershell
   Copy-Item backend\.env backend\.env.before-rotation
   ```

## 1. PostgreSQL password

`POSTGRES_PASSWORD` in `.env` is read by the `postgres` image **only when
the data volume is first created**. Changing it in `.env` alone does not
change the password of the existing database. The `ALTER USER` below does
that, and `.env` is updated to match.

```powershell
$new = python -c "import secrets; print(secrets.token_urlsafe(32))"   # [A-Za-z0-9_-] only, safe in a URL

# 1a. Change it inside the container. The SQL travels on stdin, not on the
#     command line. Inside the container psql connects over the local socket,
#     which the postgres image trusts, so the old password is not needed.
"ALTER USER truepixels WITH PASSWORD '$new';" | docker compose exec -T db psql -U truepixels -d postgres -v ON_ERROR_STOP=1 -q

# 1b. Put the same value into backend/.env: POSTGRES_PASSWORD and the password
#     part of DATABASE_URL.
$lines = Get-Content backend\.env | ForEach-Object {
  if ($_ -match '^POSTGRES_PASSWORD=') { "POSTGRES_PASSWORD=$new" }
  elseif ($_ -match '^(DATABASE_URL=[^:]+://[^:]+:)[^@]*(@.*)$') { $Matches[1] + $new + $Matches[2] }
  else { $_ }
}
[IO.File]::WriteAllLines((Resolve-Path backend\.env), [string[]]$lines)
Remove-Variable new, lines
```

Check that it worked. This prints only "db ok" or an error, with any URL
masked:

```powershell
cd backend
python -c "from app.shared.db import engine; c = engine.connect(); c.close(); print('db ok')"
cd ..
```

The scratch databases (`truepixels_test`, `truepixels_regression`) belong to
the same user, so they pick up the new password automatically.

`compose.yaml` does not need editing: it reads `backend/.env` and contains no
password.

## 2. JWT signing key

Every session token is signed with `JWT_SECRET_KEY`. Changing the key
**signs everyone out**: every token issued so far fails verification, and
users must sign in again.

```powershell
$key = python -c "import secrets; print(secrets.token_urlsafe(64))"
$lines = Get-Content backend\.env | ForEach-Object {
  if ($_ -match '^JWT_SECRET_KEY=') { "JWT_SECRET_KEY=$key" } else { $_ }
}
[IO.File]::WriteAllLines((Resolve-Path backend\.env), [string[]]$lines)
Remove-Variable key, lines
```

## 3. Verify without revealing anything

Each of these prints only True or False:

```powershell
Select-String -Path backend\.env -Pattern '^JWT_SECRET_KEY=.{80,}$' -Quiet       # set, and long
Select-String -Path backend\.env -Pattern '^POSTGRES_PASSWORD=.{40,}$' -Quiet    # set, and long
(Get-FileHash backend\.env).Hash -ne (Get-FileHash backend\.env.before-rotation).Hash   # changed
```

Then:

1. Start the API again (`cd backend; python -m uvicorn app.main:app`).
2. Confirm `GET /ready` returns 200 once the warm-up has finished.
3. Sign in again in the browser. A tab that was already signed in is sent
   to the sign-in page on its next request, because its token now fails
   verification with a 401.

Finally, delete the backup, which still holds the old values:

```powershell
Remove-Item backend\.env.before-rotation
```

## Notes

- **The old values are dead after these steps.** The old database password
  no longer authenticates. Old tokens no longer verify, and they expire
  within 8 hours (`SESSION_EXPIRE_HOURS`) anyway.
- **Known gap, to fix in Phase 6.** `compose.yaml` gives the database
  container **all** of `backend/.env` (`env_file`), and that includes
  `JWT_SECRET_KEY`. Anyone who can run `docker inspect` on the container can
  read the key. The fix is to pass the container only `POSTGRES_USER`,
  `POSTGRES_PASSWORD` and `POSTGRES_DB`.
- Do not paste either value into an issue, a chat, or a commit. If one leaks,
  repeat the relevant section.
