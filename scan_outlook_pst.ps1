param(
    [Parameter(Mandatory = $true)]
    [string]$PstFile,

    [string]$OutDir = ".\invoice_scan_output",

    [int]$MinScore = 45,

    [string]$FromDate = "",

    [string]$ToDate = "",

    [int]$MaxMessages = 0,

    [switch]$SaveCandidateAttachments
)

$ErrorActionPreference = "Stop"

function Normalize-Text([object]$Value) {
    if ($null -eq $Value) { return "" }
    return [string]$Value
}

function Test-ContainsAny([string]$Text, [string[]]$Words) {
    $lower = $Text.ToLowerInvariant()
    foreach ($word in $Words) {
        if ($lower.Contains($word)) { return $true }
    }
    return $false
}

function Get-SafeFileName([string]$Value) {
    $invalid = [IO.Path]::GetInvalidFileNameChars()
    $chars = $Value.ToCharArray() | ForEach-Object {
        if ($invalid -contains $_) { "_" } else { $_ }
    }
    $name = (-join $chars).Trim()
    if ($name) { return $name }
    return "attachment"
}

function Save-CandidateAttachments([object]$Item, [string]$SentAtText) {
    $saved = New-Object System.Collections.Generic.List[string]
    if (-not $script:SaveCandidateAttachments) {
        return $saved
    }

    $allowedExts = @(".pdf", ".xml", ".asice", ".bdoc", ".ddoc", ".xlsx", ".xls", ".csv")
    $month = if ($SentAtText -and $SentAtText.Length -ge 7) { $SentAtText.Substring(0, 7) } else { "unknown-month" }
    $targetDir = Join-Path $script:AttachmentOutputDir $month
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

    try {
        for ($i = 1; $i -le $Item.Attachments.Count; $i++) {
            $attachment = $Item.Attachments.Item($i)
            $fileName = [string]$attachment.FileName
            $ext = [IO.Path]::GetExtension($fileName).ToLowerInvariant()
            if ($allowedExts -notcontains $ext) { continue }

            $safeName = Get-SafeFileName $fileName
            $target = Join-Path $targetDir $safeName
            $counter = 2
            while (Test-Path -LiteralPath $target) {
                $base = [IO.Path]::GetFileNameWithoutExtension($safeName)
                $extension = [IO.Path]::GetExtension($safeName)
                $target = Join-Path $targetDir ("$base-$counter$extension")
                $counter += 1
            }
            $attachment.SaveAsFile($target)
            $saved.Add($target)
        }
    } catch {}
    return $saved
}

function Get-InvoiceScore([string]$Subject, [string]$SenderName, [string]$SenderEmail, [string]$Body, [string[]]$AttachmentNames) {
    $haystack = (@($Subject, $SenderName, $SenderEmail, $Body) + $AttachmentNames) -join " "
    $lower = $haystack.ToLowerInvariant()
    $score = 0
    $reasons = New-Object System.Collections.Generic.List[string]

    $invoiceWords = @("arve", "invoice", "faktuur", "bill", "rechnung", "ostuarve", "muugiarve", "kaibemaks")
    $receiptWords = @("receipt", "kviitung", "tsekk", "payment", "makse")
    $negativeWords = @("newsletter", "uudiskiri", "reklaam", "campaign")
    $invoiceExts = @(".pdf", ".xml", ".asice", ".bdoc", ".ddoc", ".xlsx", ".xls", ".csv")
    $imageExts = @(".jpg", ".jpeg", ".png")

    $invoiceHits = @($invoiceWords | Where-Object { $lower.Contains($_) })
    if ($invoiceHits.Count -gt 0) {
        $score += [Math]::Min(45, 18 + ($invoiceHits.Count * 7))
        $reasons.Add("invoice keywords: " + (($invoiceHits | Sort-Object -Unique) -join ", "))
    }

    $receiptHits = @($receiptWords | Where-Object { $lower.Contains($_) })
    if ($receiptHits.Count -gt 0) {
        $score += [Math]::Min(25, 10 + ($receiptHits.Count * 5))
        $reasons.Add("receipt/payment keywords: " + (($receiptHits | Sort-Object -Unique) -join ", "))
    }

    $invoiceAttachments = @($AttachmentNames | Where-Object { $invoiceExts -contains ([IO.Path]::GetExtension($_).ToLowerInvariant()) })
    if ($invoiceAttachments.Count -gt 0) {
        $score += 25
        $reasons.Add("invoice-like attachments: " + (($invoiceAttachments | Select-Object -First 5) -join ", "))
    }

    $namedImageAttachments = @($AttachmentNames | Where-Object {
        $ext = [IO.Path]::GetExtension($_).ToLowerInvariant()
        $name = $_.ToLowerInvariant()
        ($imageExts -contains $ext) -and ($name.Contains("arve") -or $name.Contains("invoice") -or $name.Contains("receipt") -or $name.Contains("tsekk"))
    })
    if ($namedImageAttachments.Count -gt 0) {
        $score += 15
        $reasons.Add("named image attachments: " + (($namedImageAttachments | Select-Object -First 5) -join ", "))
    }

    if ($lower -match '\b(arve|invoice|nr|no\.?)\s*[:#-]?\s*[a-z0-9][a-z0-9./-]{2,}') {
        $score += 15
        $reasons.Add("possible invoice number")
    }

    if ($lower -match '\b\d+[,.]\d{2}\s*eur\b') {
        $score += 10
        $reasons.Add("possible euro amount")
    }

    $negativeHits = @($negativeWords | Where-Object { $lower.Contains($_) })
    if ($negativeHits.Count -gt 0) {
        $score -= 25
        $reasons.Add("negative keywords: " + (($negativeHits | Sort-Object -Unique) -join ", "))
    }

    if ($score -lt 0) { $score = 0 }
    if ($score -gt 100) { $score = 100 }

    return [PSCustomObject]@{
        Score = $score
        Reasons = ($reasons -join "; ")
    }
}

function Scan-Folder([object]$Folder, [string]$FolderPath) {
    $script:FolderCount += 1
    Write-Progress -Activity "PST skannimine" -Status $FolderPath -PercentComplete -1

    $items = $Folder.Items
    try {
        $items.Sort("[ReceivedTime]", $true)
    } catch {}

    foreach ($item in $items) {
        if ($script:MaxMessages -gt 0 -and $script:TotalMessages -ge $script:MaxMessages) {
            return
        }

        if ($item.MessageClass -notlike "IPM.Note*") {
            continue
        }

        $sentAt = $null
        try { $sentAt = $item.SentOn } catch {}
        if ($null -eq $sentAt) {
            try { $sentAt = $item.ReceivedTime } catch {}
        }

        if ($script:FromDateValue -and $sentAt -and $sentAt -lt $script:FromDateValue) { continue }
        if ($script:ToDateValue -and $sentAt -and $sentAt -gt $script:ToDateValue) { continue }

        $script:TotalMessages += 1

        $attachmentNames = New-Object System.Collections.Generic.List[string]
        try {
            for ($i = 1; $i -le $item.Attachments.Count; $i++) {
                $attachmentNames.Add([string]$item.Attachments.Item($i).FileName)
            }
        } catch {}

        $body = ""
        try { $body = (Normalize-Text $item.Body) } catch {}
        if ($body.Length -gt 3000) { $body = $body.Substring(0, 3000) }

        $subject = ""
        $senderName = ""
        $senderEmail = ""
        try { $subject = Normalize-Text $item.Subject } catch {}
        try { $senderName = Normalize-Text $item.SenderName } catch {}
        try { $senderEmail = Normalize-Text $item.SenderEmailAddress } catch {}

        $result = Get-InvoiceScore -Subject $subject -SenderName $senderName -SenderEmail $senderEmail -Body $body -AttachmentNames $attachmentNames.ToArray()
        if ($result.Score -ge $script:MinScore) {
            $sentAtText = if ($sentAt) { Get-Date $sentAt -Format "yyyy-MM-dd HH:mm:ss" } else { "" }
            $savedAttachments = Save-CandidateAttachments -Item $item -SentAtText $sentAtText
            $script:Candidates.Add([PSCustomObject]@{
                score = $result.Score
                sent_at = $sentAtText
                folder = $FolderPath
                sender_name = $senderName
                sender_email = $senderEmail
                subject = $subject
                reasons = $result.Reasons
                attachment_names = ($attachmentNames -join "; ")
                attachment_paths = ($savedAttachments -join "; ")
            })
        }
    }

    foreach ($subFolder in $Folder.Folders) {
        Scan-Folder -Folder $subFolder -FolderPath ($FolderPath + "/" + $subFolder.Name)
        if ($script:MaxMessages -gt 0 -and $script:TotalMessages -ge $script:MaxMessages) {
            return
        }
    }
}

$resolvedPst = (Resolve-Path -LiteralPath $PstFile).Path
$resolvedOutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
New-Item -ItemType Directory -Force -Path $resolvedOutDir | Out-Null

$script:MinScore = $MinScore
$script:MaxMessages = $MaxMessages
$script:TotalMessages = 0
$script:FolderCount = 0
$script:Candidates = New-Object System.Collections.Generic.List[object]
$script:FromDateValue = if ($FromDate) { [datetime]::Parse($FromDate) } else { $null }
$script:ToDateValue = if ($ToDate) { [datetime]::Parse($ToDate).Date.AddDays(1).AddTicks(-1) } else { $null }
$script:SaveCandidateAttachments = [bool]$SaveCandidateAttachments
$script:AttachmentOutputDir = Join-Path $resolvedOutDir "attachments"

$outlook = New-Object -ComObject Outlook.Application
$namespace = $outlook.GetNamespace("MAPI")
$beforeStores = @($namespace.Stores | ForEach-Object { $_.FilePath })

$namespace.AddStoreEx($resolvedPst, 3)
Start-Sleep -Seconds 2

$store = $null
foreach ($candidateStore in $namespace.Stores) {
    if ($candidateStore.FilePath -eq $resolvedPst) {
        $store = $candidateStore
        break
    }
}

if ($null -eq $store) {
    throw "Outlook avas PST faili, aga store'i ei leitud: $resolvedPst"
}

$root = $store.GetRootFolder()

try {
    Scan-Folder -Folder $root -FolderPath $root.Name
} finally {
    try {
        $namespace.RemoveStore($root)
    } catch {
        Write-Warning "PST jai Outlooki profiili kulge. Selle saab Outlookis Data Files alt eemaldada."
    }
}

$csvPath = Join-Path $resolvedOutDir "invoice_candidates.csv"
$jsonPath = Join-Path $resolvedOutDir "invoice_candidates.json"

$script:Candidates |
    Sort-Object @{ Expression = "sent_at"; Descending = $true }, @{ Expression = "score"; Descending = $true } |
    Export-Csv -NoTypeInformation -Encoding UTF8 -Path $csvPath

$script:Candidates |
    Sort-Object @{ Expression = "sent_at"; Descending = $true }, @{ Expression = "score"; Descending = $true } |
    ConvertTo-Json -Depth 5 |
    Set-Content -Encoding UTF8 -Path $jsonPath

Write-Host "Kaustu loetud: $script:FolderCount"
Write-Host "Kirju loetud: $script:TotalMessages"
Write-Host "Arvekandidaate: $($script:Candidates.Count)"
Write-Host "CSV: $csvPath"
Write-Host "JSON: $jsonPath"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $Python) {
    $env:PYTHONPATH = $ProjectDir
    & $Python -m pst_invoice_finder.clean_results $csvPath --output-csv (Join-Path $resolvedOutDir "clean_invoice_candidates.csv")
}
