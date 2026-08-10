<#
.SYNOPSIS
    Mirror docs/*.md into the Obsidian vault.

.DESCRIPTION
    The repo is authoritative. Each mirrored note carries a provenance header
    saying so, plus the SHA-256 of the repo file it came from.

    That hash is the idempotence gate: a file is rewritten only when the repo
    copy actually changed. Re-running this produces no writes and no vault git
    churn, which is what makes it safe to call from a Stop hook on every turn.

    Vault edits are NOT merged back. The header says as much on every note.

.PARAMETER VaultDocs
    Destination folder. Defaults to the known vault path; override with the
    INVENTORY_VAULT_DOCS environment variable so the committed hook config does
    not depend on one machine's layout.

.PARAMETER Check
    Report what would change and exit non-zero if anything is stale. Writes
    nothing. Intended for CI or a pre-commit check.

.EXAMPLE
    ./scripts/sync-obsidian.ps1
    ./scripts/sync-obsidian.ps1 -Check
#>
[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$VaultDocs = $(
        if ($env:INVENTORY_VAULT_DOCS) { $env:INVENTORY_VAULT_DOCS }
        else { "C:\Users\mcclu\Desktop\Obsidian\John_Vault\4. Notes\Repository-Docs\inventory-app-git" }
    ),
    [switch]$Check,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is not always populated -- notably when this is launched via
# `powershell.exe -File` with a forward-slash path, which is how the Stop hook
# calls it. Fall back to the invocation path before giving up.
if (-not $RepoRoot) {
    $scriptPath = if ($PSScriptRoot) { $PSScriptRoot }
                  elseif ($MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path }
                  else { $null }
    if (-not $scriptPath) { throw "Cannot resolve script location; pass -RepoRoot explicitly." }
    $RepoRoot = Split-Path -Parent $scriptPath
}

$docsDir = Join-Path $RepoRoot 'docs'
$target  = Join-Path $VaultDocs 'reviews'

# Vault-only wikilinks, added per note. These are the reason the mirror is
# generated rather than copied -- a plain copy would drop them every sync.
$related = @{
    'api-hardening-checklist.md' = '[[Gap Audit]] is the FastAPI-specific exposure audit this checklist was built from. Shipped items live in [[api-hardening-archive]].'
    'api-hardening-archive.md'   = 'The live queue this was split out of is [[api-hardening-checklist]].'
    'handoff.md'                 = 'Session-by-session detail lives in [[session-log]]. Open items are indexed in [[open-work]].'
    'open-work.md'               = 'Owning docs: [[improvement-tracker]], [[api-hardening-checklist]], [[ux-review]].'
    'ux-review.md'               = 'Completed July 2026 items live in [[ux-review-archive]].'
    'ux-review-archive.md'       = 'The open findings this was split out of are in [[ux-review]].'
}

function Get-FileSha256([string]$path) {
    (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLower()
}

function Get-MirrorSha([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    $head = Get-Content $path -TotalCount 40 -ErrorAction SilentlyContinue
    foreach ($line in $head) {
        if ($line -match 'sync-source-sha256:\s*([0-9a-f]{64})') { return $Matches[1] }
    }
    return $null
}

if (-not (Test-Path $docsDir)) { throw "docs/ not found under '$RepoRoot'." }
if (-not (Test-Path $target)) {
    if ($Check) { throw "Vault target '$target' does not exist." }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
}

$sha = try { (git -C $RepoRoot rev-parse --short HEAD 2>$null).Trim() } catch { 'unknown' }
if (-not $sha) { $sha = 'unknown' }
$stamp = Get-Date -Format 'yyyy-MM-ddTHH:mm'
$today = Get-Date -Format 'yyyy-MM-dd'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$written = @()
$skipped = @()

foreach ($doc in (Get-ChildItem $docsDir -Filter *.md -File | Sort-Object Name)) {
    $srcHash = Get-FileSha256 $doc.FullName
    $dest    = Join-Path $target $doc.Name

    if ((Get-MirrorSha $dest) -eq $srcHash) { $skipped += $doc.Name; continue }

    $written += $doc.Name
    if ($Check) { continue }

    $lines = @(Get-Content $doc.FullName -Encoding UTF8)
    $title = [System.IO.Path]::GetFileNameWithoutExtension($doc.Name)

    $header = @(
        '---'
        "title: `"$title`""
        'aliases: []'
        "updated: $today"
        'status: stable'
        'type: reference'
        'project: "John_Vault"'
        'area: "repository-docs"'
        'tags:'
        '  - project/john-vault'
        '  - area/repository-docs'
        '  - type/reference'
        '  - status/stable'
        'related: []'
        "summary: `"Mirror of docs/$($doc.Name) from the inventory_app_git repository.`""
        'source: "agent"'
        '---'
        ''
    )

    $provenance = @(
        ''
        "> **Vault mirror.** The authoritative copy is ``docs/$($doc.Name)`` in the"
        '> `inventory_app_git` repository. Edit the repo copy and re-sync -- never the'
        '> reverse. Edits made here are overwritten on the next sync.'
        '>'
        "> Synced $stamp local, from repo commit ``$sha``."
    )
    if ($related.ContainsKey($doc.Name)) {
        $provenance += '>'
        $provenance += "> Related: $($related[$doc.Name])"
    }
    $provenance += "> <!-- sync-source-sha256: $srcHash -->"
    $provenance += ''

    # Slot the provenance under the document's own H1 so the note still opens
    # with its real title in Obsidian's preview and graph.
    if ($lines.Count -gt 1 -and $lines[0] -match '^#\s') {
        $body = @($lines[0]) + $provenance + $lines[1..($lines.Count - 1)]
    } else {
        $body = $provenance + $lines
    }

    $text = (($header + $body) -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText($dest, $text, $utf8NoBom)
}

if (-not $Quiet) {
    if ($Check) {
        if ($written.Count -gt 0) {
            Write-Host "STALE ($($written.Count)): $($written -join ', ')"
        } else {
            Write-Host "Vault mirror is current ($($skipped.Count) file(s), commit $sha)."
        }
    } elseif ($written.Count -gt 0) {
        Write-Host "Synced $($written.Count) file(s) from $sha`: $($written -join ', ')"
    } else {
        Write-Host "Vault mirror already current ($($skipped.Count) file(s), commit $sha)."
    }
}

if ($Check -and $written.Count -gt 0) { exit 1 }
exit 0
