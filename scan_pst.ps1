param(
    [Parameter(Mandatory = $true)]
    [string]$PstFile,

    [string]$OutDir = ".\invoice_scan_output",

    [int]$MinScore = 45,

    [switch]$NoAttachments
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @(
    "-m", "pst_invoice_finder.cli",
    "scan", $PstFile,
    "--out-dir", $OutDir,
    "--min-score", "$MinScore"
)

if ($NoAttachments) {
    $argsList += "--no-attachments"
}

& $Python @argsList
exit $LASTEXITCODE
