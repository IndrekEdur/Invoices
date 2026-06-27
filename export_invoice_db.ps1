param(
    [string]$DbPath = ".\invoice_register.sqlite",
    [string]$OutputCsv = ".\invoice_register_export.csv"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

& $Python -m pst_invoice_finder.export_db --db $DbPath --output-csv $OutputCsv
exit $LASTEXITCODE
