param(
    [Parameter(Mandatory = $true)]
    [string]$InputCsv,

    [string]$DbPath = ".\invoice_register.sqlite",

    [int]$Limit = 0,

    [switch]$AutoKeepConfirmed
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @(
    "-m", "pst_invoice_finder.review_invoices",
    $InputCsv,
    "--db", $DbPath
)

if ($Limit -gt 0) {
    $argsList += @("--limit", "$Limit")
}

if ($AutoKeepConfirmed) {
    $argsList += "--auto-keep-confirmed"
}

& $Python @argsList
exit $LASTEXITCODE
