param(
    [string]$InputCsv = ".\invoice_scan_output_outlook_refined\clean_invoice_candidates.csv",
    [string]$DbPath = ".\invoice_register.sqlite",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

$env:PYTHONPATH = $ProjectDir

& $Python -m pst_invoice_finder.web_app --csv $InputCsv --db $DbPath --port $Port
