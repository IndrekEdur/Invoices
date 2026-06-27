param(
    [Parameter(Mandatory = $true)]
    [string]$MeritCsv,

    [string]$BankCsv = "",

    [string]$BankDb = "",

    [string]$MailDb = ".\invoice_register.sqlite",

    [string]$OutDir = ".\merit_bank_mail_compare"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @('-m', 'pst_invoice_finder.compare_merit_bank_mail', '--merit-csv', $MeritCsv, '--mail-db', $MailDb, '--out-dir', $OutDir)
if ($BankDb) {
    $argsList += @('--bank-db', $BankDb)
} elseif ($BankCsv) {
    $argsList += @('--bank-csv', $BankCsv)
} else {
    throw "Anna kas -BankDb või -BankCsv"
}

& $Python @argsList
exit $LASTEXITCODE
