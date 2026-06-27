param(
    [Parameter(Mandatory = $true)]
    [string]$XlsxFile,

    [string]$OutputCsv = ".\merit_purchase_invoices.csv",

    [int]$Months = 6
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

& $Python -m pst_invoice_finder.merit_import $XlsxFile --output-csv $OutputCsv --months $Months
exit $LASTEXITCODE
