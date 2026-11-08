param(
    [string]$DocumentPath = (Join-Path $PSScriptRoot 'WIOT_STM32_Node_Software_Design_V1.2.docx'),
    [string]$QaPdfPath = (Join-Path $PSScriptRoot 'tmp/design/word-export-v1.2.pdf')
)
$ErrorActionPreference = 'Stop'
$designFile = (Resolve-Path -LiteralPath $DocumentPath).Path
$designPdf = [System.IO.Path]::GetFullPath($QaPdfPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $designPdf) | Out-Null
$designWord = $null
$designDoc = $null
try {
    $designWord = New-Object -ComObject Word.Application
    $designWord.Visible = $false
    $designWord.DisplayAlerts = 0
    $designDoc = $designWord.Documents.Open($designFile, $false, $false)
    $designDoc.Fields.Update() | Out-Null
    foreach ($designToc in $designDoc.TablesOfContents) { $designToc.Update() }
    $designDoc.Repaginate()
    foreach ($designToc in $designDoc.TablesOfContents) { $designToc.UpdatePageNumbers() }
    $designDoc.Save()
    $designDoc.ExportAsFixedFormat($designPdf, 17)
    Write-Output ('Pages: ' + $designDoc.ComputeStatistics(2))
    Write-Output ('QA export: ' + $designPdf)
}
finally {
    if ($null -ne $designDoc) { $designDoc.Close(0) }
    if ($null -ne $designWord) { $designWord.Quit() }
    if ($null -ne $designDoc) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($designDoc) }
    if ($null -ne $designWord) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($designWord) }
}
