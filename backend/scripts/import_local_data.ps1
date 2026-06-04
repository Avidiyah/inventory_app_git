<#
.SYNOPSIS
  One-time copy of the LOCAL inventory data into the deployed (Render)
  Postgres database.

.DESCRIPTION
  Dumps the data (rows only -- the schema is already created on Render by
  `alembic upgrade head` in the container entrypoint) from the local
  database named in backend/.env and loads it into the remote database
  you pass in.

  Carried over: users (with their scrypt password hashes), items,
  transactions. Deliberately skipped:
    * sessions        -- local login tokens; invalid and unsafe remotely
    * alembic_version -- already stamped by the remote migration step

  Because the table primary keys are application-generated UUIDs (not
  serial sequences), no sequence reset is needed.

.PARAMETER RemoteUrl
  The Render *External* database connection string, e.g.
  postgresql://USER:PASS@HOST.oregon-postgres.render.com/DBNAME
  Copy it from the Render dashboard -> your database -> "External
  Database URL".

.PARAMETER LocalUrl
  Optional override for the source database. Defaults to DATABASE_URL in
  backend/.env (with the SQLAlchemy "+psycopg" driver tag stripped).

.EXAMPLE
  .\scripts\import_local_data.ps1 -RemoteUrl "postgresql://u:p@host.render.com/db"

.NOTES
  Run from the backend/ directory. Requires the PostgreSQL client tools
  (pg_dump, psql). This is a one-shot migration -- re-running it against a
  database that already holds these rows will fail on duplicate keys,
  which is the intended safety net.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RemoteUrl,

    [string]$LocalUrl
)

$ErrorActionPreference = "Stop"

# --- Locate pg_dump / psql -------------------------------------------------
function Resolve-PgTool([string]$name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\$name.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($candidates) { return $candidates[0].FullName }
    throw "$name not found. Install the PostgreSQL client tools or add them to PATH."
}

$pgDump = Resolve-PgTool "pg_dump"
$psql   = Resolve-PgTool "psql"
Write-Host "Using pg_dump: $pgDump"
Write-Host "Using psql:    $psql"

# --- Resolve the local source URL -----------------------------------------
if (-not $LocalUrl) {
    $envPath = Join-Path $PSScriptRoot "..\.env"
    if (-not (Test-Path $envPath)) { throw "backend/.env not found; pass -LocalUrl explicitly." }
    $line = Get-Content $envPath | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
    if (-not $line) { throw "DATABASE_URL not found in backend/.env; pass -LocalUrl explicitly." }
    $LocalUrl = ($line -replace '^\s*DATABASE_URL\s*=', '').Trim().Trim('"')
}

# pg_dump/psql speak libpq URIs, which do not understand the SQLAlchemy
# "+psycopg" driver tag. Strip it.
$LocalUrl  = $LocalUrl  -replace '\+psycopg', ''
$RemoteUrl = $RemoteUrl -replace '\+psycopg', ''

function Hide-Secret([string]$url) { $url -replace '//[^@]*@', '//***:***@' }
Write-Host "Source (local):  $(Hide-Secret $LocalUrl)"
Write-Host "Target (remote): $(Hide-Secret $RemoteUrl)"

# --- Dump local data -------------------------------------------------------
$dumpFile = Join-Path $env:TEMP "inventory_data_$(Get-Date -Format yyyyMMdd_HHmmss).sql"
Write-Host "`nDumping local data to $dumpFile ..."
& $pgDump `
    --data-only `
    --no-owner `
    --no-privileges `
    --exclude-table=alembic_version `
    --exclude-table=sessions `
    --file=$dumpFile `
    $LocalUrl
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE)." }

# --- Load into remote ------------------------------------------------------
Write-Host "Loading into remote database (single transaction) ..."
& $psql --set=ON_ERROR_STOP=1 --single-transaction --file=$dumpFile $RemoteUrl
if ($LASTEXITCODE -ne 0) { throw "psql load failed (exit $LASTEXITCODE). No rows were committed." }

Write-Host "`nDone. Local users, items, and transactions are now in the remote database." -ForegroundColor Green
Write-Host "Dump file left at: $dumpFile (delete it -- it contains password hashes)."
