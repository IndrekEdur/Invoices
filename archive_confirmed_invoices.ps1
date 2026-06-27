param(
    [string]$DbPath = ".\invoice_register.sqlite",
    [string]$ArchiveRoot = ".\confirmed_invoice_archive",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @(
    "-m", "pst_invoice_finder.archive_confirmed",
    "--db", $DbPath,
    "--archive-root", $ArchiveRoot
)

if ($DryRun) {
    $argsList += "--dry-run"
}

& $Python @argsList
exit $LASTEXITCODE
