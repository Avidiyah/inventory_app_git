<#
.SYNOPSIS
    Mirror docs/ into the Obsidian vault.

.DESCRIPTION
    The repo is authoritative. Each mirrored note carries a provenance header
    saying so, plus the SHA-256 of the repo file it came from.

    That hash is the idempotence gate: a file is rewritten only when the repo
    copy actually changed. Re-running this produces no writes and no vault git
    churn, which is what makes it safe to call from a Stop hook on every turn.

    Four folders are mirrored, each non-recursively, into a matching vault
    folder: docs/ -> reviews/, and the three levels of docs/superpowers/ ->
    superpowers/. A source folder that does not exist is skipped, so retiring
    docs/superpowers/ again needs no change here.

    Vault edits are NOT merged back. The header says as much on every note.

    Deletions are NOT propagated: a doc removed from the repo lingers in the
    vault, which is not git-backed, so an automatic delete could destroy the
    only copy of something. Orphans are reported instead -- remove them by hand
    once you have looked at them.

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

# The mirror set. Each entry is one repo folder mirrored non-recursively into
# one vault folder; nesting is expressed by listing the child folders, so no
# file is picked up twice. `Type` drives the note's frontmatter type/tag.
#
# `Related` marks the folder whose files may draw a wikilink from $related
# below -- only the docs root has hand-written links.
$mirrors = @(
    [pscustomobject]@{
        Label   = 'docs'
        Source  = $docsDir
        Dest    = Join-Path $VaultDocs 'reviews'
        Type    = 'reference'
        Related = $true
    }
    [pscustomobject]@{
        Label   = 'docs/superpowers'
        Source  = Join-Path $docsDir 'superpowers'
        Dest    = Join-Path $VaultDocs 'superpowers'
        Type    = 'note'
        Related = $false
    }
    [pscustomobject]@{
        Label   = 'docs/superpowers/plans'
        Source  = Join-Path $docsDir 'superpowers\plans'
        Dest    = Join-Path $VaultDocs 'superpowers\plans'
        Type    = 'plan'
        Related = $false
    }
    [pscustomobject]@{
        Label   = 'docs/superpowers/specs'
        Source  = Join-Path $docsDir 'superpowers\specs'
        Dest    = Join-Path $VaultDocs 'superpowers\specs'
        Type    = 'spec'
        Related = $false
    }
)

# Vault-only wikilinks, added per note. These are the reason the mirror is
# generated rather than copied -- a plain copy would drop them every sync.
#
# Keys MUST name a file that still exists in docs/. A key for a deleted doc is
# dead weight, but a *value* naming a deleted note is worse: it renders as a
# dangling wikilink in the vault. Rewritten 2026-08-16, when the previous map
# was found still pointing at the six docs consolidated away on 2026-08-10.
$related = @{
    'project-summary.md' = 'Routing authority for this folder -- see its *Documentation map*. Behaviour detail is in [[current-state]]; the backlog is [[open-work]].'
    'current-state.md'   = 'Per-endpoint contracts live in [[endpoint-map]]. Anything not yet true of the system belongs in [[open-work]], not here.'
    'endpoint-map.md'    = 'The invariants these endpoints must uphold are in [[current-state]].'
    'open-work.md'       = 'The **only** backlog: if an item is not here, it is not open. What the system already does is in [[current-state]]. Session narrative: [[session-log]].'
    'notification-events.md'          = 'The living register of what notifies whom. How to wire a new one: [[adding-a-notification-trigger]].'
    'adding-a-notification-trigger.md' = 'The procedure. What is already wired is registered in [[notification-events]].'
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
# The vault root must already exist -- if it does not, this is the wrong machine
# or a bad -VaultDocs, and creating it would scatter a fresh tree somewhere odd.
# Individual mirror folders below are created on demand.
if (-not (Test-Path $VaultDocs)) { throw "Vault folder '$VaultDocs' does not exist." }

$sha = try { (git -C $RepoRoot rev-parse --short HEAD 2>$null).Trim() } catch { 'unknown' }
if (-not $sha) { $sha = 'unknown' }
$stamp = Get-Date -Format 'yyyy-MM-ddTHH:mm'
$today = Get-Date -Format 'yyyy-MM-dd'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$written = @()
$skipped = @()
$orphans = @()

foreach ($mirror in $mirrors) {
    # A source folder that no longer exists is not an error -- docs/superpowers/
    # has been retired once already and may be again.
    if (-not (Test-Path $mirror.Source)) { continue }

    $docs = @(Get-ChildItem $mirror.Source -Filter *.md -File | Sort-Object Name)

    if (Test-Path $mirror.Dest) {
        $sourceNames = @($docs | ForEach-Object { $_.Name })
        foreach ($stale in (Get-ChildItem $mirror.Dest -Filter *.md -File | Sort-Object Name)) {
            if ($sourceNames -notcontains $stale.Name) {
                $orphans += "$($mirror.Label)/$($stale.Name)"
            }
        }
    } elseif ($docs.Count -gt 0 -and -not $Check) {
        New-Item -ItemType Directory -Path $mirror.Dest -Force | Out-Null
    }

    foreach ($doc in $docs) {
        $relPath = "$($mirror.Label)/$($doc.Name)"
        $srcHash = Get-FileSha256 $doc.FullName
        $dest    = Join-Path $mirror.Dest $doc.Name

        if ((Get-MirrorSha $dest) -eq $srcHash) { $skipped += $relPath; continue }

        $written += $relPath
        if ($Check) { continue }

        $lines = @(Get-Content $doc.FullName -Encoding UTF8)
        $title = [System.IO.Path]::GetFileNameWithoutExtension($doc.Name)
        $type  = $mirror.Type

        $header = @(
            '---'
            "title: `"$title`""
            'aliases: []'
            "updated: $today"
            'status: stable'
            "type: $type"
            'project: "John_Vault"'
            'area: "repository-docs"'
            'tags:'
            '  - project/john-vault'
            '  - area/repository-docs'
            "  - type/$type"
            '  - status/stable'
            'related: []'
            "summary: `"Mirror of $relPath from the inventory_app_git repository.`""
            'source: "agent"'
            '---'
            ''
        )

        $provenance = @(
            ''
            "> **Vault mirror.** The authoritative copy is ``$relPath`` in the"
            '> `inventory_app_git` repository. Edit the repo copy and re-sync -- never the'
            '> reverse. Edits made here are overwritten on the next sync.'
            '>'
            "> Synced $stamp local, from repo commit ``$sha``."
        )
        if ($mirror.Related -and $related.ContainsKey($doc.Name)) {
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

    # Reported, never deleted: the vault is not git-backed, so removing a note
    # here could destroy the only copy. This is a prompt to look, not a failure.
    if ($orphans.Count -gt 0) {
        Write-Host "ORPHANS ($($orphans.Count)) -- in the vault, gone from the repo; remove by hand after checking: $($orphans -join ', ')"
    }
}

if ($Check -and $written.Count -gt 0) { exit 1 }
exit 0
