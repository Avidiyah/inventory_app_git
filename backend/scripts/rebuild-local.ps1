# Rebuild the inventory-app image and replace the local inventory-local container.
# Run from anywhere: .\scripts\rebuild-local.ps1   (never edits .env; writes a copy to $env:TEMP)
# Docker writes progress to stderr, which 'Stop' would treat as an error; check exit codes instead.
Set-Location (Split-Path $PSScriptRoot -Parent)

# Container-side copy of .env: Postgres lives on the host, not at localhost.
$envCopy = Join-Path $env:TEMP 'inventory.docker.env'
(Get-Content .env) -replace '@localhost:', '@host.docker.internal:' -replace '@127\.0\.0\.1:', '@host.docker.internal:' |
    Set-Content -Encoding ascii $envCopy

docker build -t inventory-app .
if ($LASTEXITCODE -ne 0) { throw 'docker build failed; old container left running' }

docker rm -f inventory-local 2>$null | Out-Null
docker run -d --name inventory-local --memory=2g -p 8124:8124 --env-file $envCopy inventory-app
if ($LASTEXITCODE -ne 0) { throw 'docker run failed' }

Start-Sleep 10
docker logs inventory-local --tail 15
