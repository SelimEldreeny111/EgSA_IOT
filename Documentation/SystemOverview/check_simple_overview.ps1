param([switch]$Candidate, [switch]$EditSmokeTest)
# Render in PowerPoint; editability checks operate on a separate temporary copy.
$ErrorActionPreference = 'Stop'
$simpleTemp = Join-Path $PSScriptRoot 'tmp/simple'
$simplePath = if ($Candidate) { Join-Path $simpleTemp 'candidate.pptx' } else {
    Join-Path $PSScriptRoot 'output/WIOT_Software_Overview_Simple_v2.0.pptx'
}
$simpleWasRunning = $null -ne (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$simpleApp = $null
$simpleDeck = $null
try {
    $simpleApp = New-Object -ComObject PowerPoint.Application
    $simpleDeck = $simpleApp.Presentations.Open($simplePath, -1, 0, 0)
    if ($simpleDeck.Slides.Count -ne 2) { throw 'Expected two slides' }
    $simpleDeck.Slides.Item(1).Export((Join-Path $simpleTemp 'overview-preview.png'), 'PNG', 3200, 1800)
    $simpleDeck.Slides.Item(2).Export((Join-Path $simpleTemp 'illustration-preview.png'), 'PNG', 1920, 1080)
    if (-not $Candidate) {
        $simpleDeck.Slides.Item(1).Export((Join-Path $PSScriptRoot 'output/WIOT_Software_Overview_Simple_v2.0.png'), 'PNG', 6400, 3600)
    }
    $simpleDeck.Close()
    $simpleDeck = $null
    if ($EditSmokeTest) {
        $simpleCopy = Join-Path $simpleTemp 'edit-smoke-test.pptx'
        Copy-Item -LiteralPath $simplePath -Destination $simpleCopy -Force
        $simpleDeck = $simpleApp.Presentations.Open($simpleCopy, 0, 0, 0)
        $simpleHeading = $simpleDeck.Slides.Item(1).Shapes.Item('Heading node')
        $simpleText = $simpleHeading.TextFrame.TextRange.Text
        $simpleHeading.TextFrame.TextRange.Text = 'EDIT TEST'
        if ($simpleHeading.TextFrame.TextRange.Text -ne 'EDIT TEST') { throw 'Text is not editable' }
        $simpleHeading.TextFrame.TextRange.Text = $simpleText
        $simpleArrow = $simpleDeck.Slides.Item(1).Shapes.Item('Flow commands return')
        if ($simpleArrow.Nodes.Count -lt 2) { throw 'Arrow has no editable points' }
        $simplePoints = $simpleArrow.Nodes.Item(1).Points
        $simpleRow = $simplePoints.GetLowerBound(0)
        $simpleCol = $simplePoints.GetLowerBound(1)
        $simpleX = [single]$simplePoints.GetValue($simpleRow, $simpleCol)
        $simpleY = [single]$simplePoints.GetValue($simpleRow, ($simpleCol + 1))
        $simpleArrow.Nodes.SetPosition(1, ($simpleX + 1), $simpleY)
        $simpleArrow.Nodes.SetPosition(1, $simpleX, $simpleY)
        $simpleDeck.Save()
        $simpleDeck.Close()
        $simpleDeck = $simpleApp.Presentations.Open($simpleCopy, -1, 0, 0)
        if ($simpleDeck.Slides.Item(1).Shapes.Item('Heading node').TextFrame.TextRange.Text -ne $simpleText) {
            throw 'Text did not survive save/reopen'
        }
        Write-Output 'PASS native text/arrow editing and save/reopen in a separate copy'
    }
    Write-Output 'PASS both slides rendered in Microsoft PowerPoint'
} finally {
    if ($null -ne $simpleDeck) { $simpleDeck.Close() }
    if ($null -ne $simpleApp -and -not $simpleWasRunning) { $simpleApp.Quit() }
}
