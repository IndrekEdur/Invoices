param(
    [Parameter(Mandatory = $true)]
    [string]$XmlFile,

    [string]$OutputCsv = ".\bank_statement_transactions.csv",

    [string]$Db = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @('-m', 'pst_invoice_finder.bank_import', $XmlFile)
if ($OutputCsv) {
    $argsList += @('--output-csv', $OutputCsv)
}
if ($Db) {
    $argsList += @('--db', $Db)
}

& $Python @argsList
exit $LASTEXITCODE
