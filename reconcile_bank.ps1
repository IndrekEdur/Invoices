param(
    [Parameter(Mandatory = $true)]
    [string]$BankCsv,

    [string]$DbPath = ".\invoice_register.sqlite",

    [string]$OutDir = ".\bank_invoice_reconciliation"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

& $Python -m pst_invoice_finder.reconcile_bank --bank-csv $BankCsv --db $DbPath --out-dir $OutDir
exit $LASTEXITCODE
