<#
.SYNOPSIS
    Ralph Loop harness for the Tralala project.

.DESCRIPTION
    Repeatedly selects the highest-priority unblocked pending story from .ralph/prd.json and
    invokes an agent command with per-iteration context. The harness never marks stories done:
    an iteration proves completion by running validation, updating prd.json, committing and
    appending to .ralph/progress.txt.

.EXAMPLE
    $env:TRALALA_RALPH_AGENT_CMD = "my-agent"
    .\scripts\ralph\run.ps1 -MaxIterations 5
#>
[CmdletBinding()]
param(
    [int]$MaxIterations = 10,
    [int]$MaxRetriesPerStory = 2,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$prdPath = Join-Path $repoRoot ".ralph\prd.json"
$progressPath = Join-Path $repoRoot ".ralph\progress.txt"
$promptPath = Join-Path $repoRoot ".ralph\prompt.md"

if (-not (Test-Path $prdPath)) { throw "Missing $prdPath" }

function Get-ReadyStory {
    param($Prd)
    $done = @($Prd.stories | Where-Object { $_.status -eq "done" } | ForEach-Object { $_.id })
    $Prd.stories |
        Where-Object { $_.status -eq "pending" } |
        Where-Object { -not ($_.depends_on | Where-Object { $done -notcontains $_ }) } |
        Sort-Object priority |
        Select-Object -First 1
}

$agentCommand = $env:TRALALA_RALPH_AGENT_CMD
$attempts = @{}
$iteration = 0

while ($iteration -lt $MaxIterations) {
    $prd = Get-Content $prdPath -Raw | ConvertFrom-Json
    $story = Get-ReadyStory -Prd $prd
    if (-not $story) {
        Write-Host "No pending unblocked stories. Ralph loop complete."
        break
    }

    $current = 0
    if ($attempts.ContainsKey($story.id)) { $current = $attempts[$story.id] }
    if ($current -ge $MaxRetriesPerStory) {
        Write-Warning "Story $($story.id) exceeded the retry budget ($MaxRetriesPerStory); stopping."
        break
    }

    $iteration++
    $title = "$($story.id) $($story.title)"

    if ($DryRun) {
        Write-Host "[dry-run] iteration $iteration -> $title (attempt $($current + 1))"
        break
    }

    $criteria = ($story.acceptance_criteria | ForEach-Object { "  - $_" }) -join "`n"
    $context = @"
$(Get-Content $promptPath -Raw)

## Selected story

- id: $($story.id)
- title: $($story.title)
- description: $($story.description)
- acceptance criteria:
$criteria
- attempt: $($current + 1) of $($MaxRetriesPerStory + 1)
"@

    $contextFile = Join-Path $repoRoot ".ralph\iteration-context.md"
    Set-Content -Path $contextFile -Value $context -Encoding utf8

    if (-not $agentCommand) {
        Write-Host "TRALALA_RALPH_AGENT_CMD is not set."
        Write-Host "Iteration context for $title written to $contextFile."
        break
    }

    & cmd /c "$agentCommand `"$contextFile`""
    $exit = $LASTEXITCODE

    $prdAfter = Get-Content $prdPath -Raw | ConvertFrom-Json
    $storyAfter = $prdAfter.stories | Where-Object { $_.id -eq $story.id }
    if ($exit -ne 0 -or $storyAfter.status -ne "done") {
        $attempts[$story.id] = $current + 1
        Add-Content -Path $progressPath -Value "## $(Get-Date -AsUTC -Format 'yyyy-MM-ddTHH:mm:ssZ') — $($story.id) — iteration failed (exit $exit, attempt $($current + 1))"
        continue
    }

    Add-Content -Path $progressPath -Value "## $(Get-Date -AsUTC -Format 'yyyy-MM-ddTHH:mm:ssZ') — $($story.id) — completed by Ralph iteration"
}

Write-Host "Ralph loop finished after $iteration iteration(s)."
