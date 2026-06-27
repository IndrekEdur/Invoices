param(
    [string]$DbPath = ".\invoice_register.sqlite",
    [string]$Status = "pending",
    [int]$InvoiceId = 0,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

$argsList = @("-m", "pst_invoice_finder.invoice_extract", "--db", $DbPath, "--status", $Status)
if ($InvoiceId -gt 0) { $argsList += @("--invoice-id", "$InvoiceId") }
if ($Limit -gt 0) { $argsList += @("--limit", "$Limit") }

& $Python @argsList
exit $LASTEXITCODE
