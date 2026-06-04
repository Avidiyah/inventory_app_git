# Deploying the Inventory app to Render

This deploys the whole stack as **one** Render service (FastAPI serves both
the API and the static SPA) plus **one** managed Postgres. Your workforce
opens the resulting `https://…onrender.com` URL on their phones.

## What's in the repo for this

| File | Purpose |
|------|---------|
| `backend/Dockerfile` | Builds the image; installs `libzbar0` (native dep for barcode scanning). |
| `backend/entrypoint.sh` | Runs `alembic upgrade head`, then starts uvicorn on `$PORT`. |
| `backend/.dockerignore` | Keeps `venv/`, `.env`, tests out of the build. |
| `render.yaml` | Blueprint: the web service + the Postgres database + env vars. |
| `backend/scripts/import_local_data.ps1` | One-time copy of your local data into Render's DB. |

Code changes that make this safe in production:
- `DATABASE_URL` scheme is normalized to psycopg 3 (`app/database.py`), so
  Render's `postgresql://…` works unchanged.
- SQL echo is off unless `SQL_ECHO=true`.
- `COOKIE_SECURE=true` is set in `render.yaml` (HTTPS-only session cookie).
- Static assets are served `Cache-Control: no-cache` to avoid the blank-page
  stale-`main.js` problem on phones.

## One-time setup

### 1. Push the branch to GitHub
Render deploys from a Git remote. Make sure this repo (with the files above)
is on GitHub and the branch is pushed.

### 2. Create the Blueprint
Render dashboard → **New** → **Blueprint** → pick this repo → confirm.
Render reads `render.yaml` and creates **inventory-app** (web) and
**inventory-db** (Postgres). `DATABASE_URL` is wired automatically.

> When creating the database, choose a Postgres **version ≥ your local
> version** (local is 18) if the option appears, so the dump restores cleanly.

The first deploy builds the image and runs the migration, leaving an **empty
but fully-structured** database.

### 3. Import your existing data
From the `backend/` directory, with the project venv or any PowerShell:

```powershell
# Get the value from: Render → inventory-db → "External Database URL"
.\scripts\import_local_data.ps1 -RemoteUrl "postgresql://USER:PASS@HOST.render.com/DBNAME"
```

This copies **users (with password hashes), items, and transactions** from
your local DB into Render. It skips local login `sessions` and the
`alembic_version` row. It's a one-shot — re-running errors on duplicate keys
by design.

Afterwards, **delete the temp dump file** it prints (it contains password
hashes).

### 4. Verify
- Open the service URL → you should get the login screen.
- Log in with an existing account → the app loads.
- Optional: as Owner/Admin, hit `/db-test` to confirm the DB wiring.

## Day-2 notes
- **Deploys:** push to the branch → Render rebuilds and re-runs migrations
  automatically (`autoDeploy: true`).
- **Schema changes:** create the Alembic migration as usual; it's applied on
  the next deploy by `entrypoint.sh`. No data re-import needed.
- **Free tier caveats:** the web service sleeps after ~15 min idle (first
  request then takes ~30 s); the free Postgres **expires after 90 days** —
  upgrade to a paid instance before then to keep the data.
- **Adding users going forward:** use the in-app Create User screen (as
  Owner/Admin) — no need to touch the local DB again.
