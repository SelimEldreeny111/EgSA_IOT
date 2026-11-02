param([switch]$EditSmokeTest)
# Read-only render of the deliverable; optional edits affect a separate copy.
$ErrorActionPreference = 'Stop'
$overviewPath = Join-Path $PSScriptRoot 'output/WIOT_System_Architecture_Overview_v1.0.pptx'
$overviewTemp = Join-Path $PSScriptRoot 'tmp'
$overviewWasRunning = $null -ne (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$overviewApp = $null
$overviewDeck = $null
try {
    $overviewApp = New-Object -ComObject PowerPoint.Application
    $overviewDeck = $overviewApp.Presentations.Open($overviewPath, -1, 0, 0)
    if ($overviewDeck.Slides.Count -ne 2) { throw 'Expected exactly two slides' }
    $overviewDeck.Slides.Item(1).Export((Join-Path $PSScriptRoot 'output/WIOT_Software_Architecture.png'), 'PNG', 6400, 3600)
    $overviewDeck.Slides.Item(1).Export((Join-Path $overviewTemp 'architecture-preview.png'), 'PNG', 3200, 1800)
    $overviewDeck.Slides.Item(2).Export((Join-Path $overviewTemp 'illustration-slide-preview.png'), 'PNG', 1920, 1080)
    $overviewDeck.Close()
    $overviewDeck = $null
    if ($EditSmokeTest) {
        $overviewCopy = Join-Path $overviewTemp 'edit-smoke-test.pptx'
        Copy-Item -LiteralPath $overviewPath -Destination $overviewCopy -Force
        $overviewDeck = $overviewApp.Presentations.Open($overviewCopy, 0, 0, 0)
        $overviewHeading = $overviewDeck.Slides.Item(1).Shapes.Item('Heading loop')
        $overviewText = $overviewHeading.TextFrame.TextRange.Text
        $overviewHeading.TextFrame.TextRange.Text = 'EDIT TEST'
        if ($overviewHeading.TextFrame.TextRange.Text -ne 'EDIT TEST') { throw 'Text is not editable' }
        $overviewHeading.TextFrame.TextRange.Text = $overviewText
        $overviewArrow = $overviewDeck.Slides.Item(1).Shapes.Item('Arrow boot')
        if ($overviewArrow.Nodes.Count -lt 2) { throw 'Arrow is not an editable freeform' }
        $overviewPoints = $overviewArrow.Nodes.Item(1).Points
        $overviewRow = $overviewPoints.GetLowerBound(0)
        $overviewCol = $overviewPoints.GetLowerBound(1)
        $overviewX = [single]$overviewPoints.GetValue($overviewRow, $overviewCol)
        $overviewY = [single]$overviewPoints.GetValue($overviewRow, ($overviewCol + 1))
        $overviewArrow.Nodes.SetPosition(1, ($overviewX + 1), $overviewY)
        $overviewArrow.Nodes.SetPosition(1, $overviewX, $overviewY)
        $overviewDeck.Save()
        $overviewDeck.Close()
        $overviewDeck = $overviewApp.Presentations.Open($overviewCopy, -1, 0, 0)
        if ($overviewDeck.Slides.Item(1).Shapes.Item('Heading loop').TextFrame.TextRange.Text -ne $overviewText) {
            throw 'Text did not survive save/reopen'
        }
        Write-Output 'PASS: native text edit, arrow-point edit and save/reopen'
    }
    Write-Output 'PASS: both slides rendered by Microsoft PowerPoint; architecture PNG is 6400 x 3600'
} finally {
    if ($null -ne $overviewDeck) { $overviewDeck.Close() }
    if ($null -ne $overviewApp -and -not $overviewWasRunning) { $overviewApp.Quit() }
}
