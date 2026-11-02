param(
    [string]$PresentationPath = (Join-Path $PSScriptRoot 'output/pptx/WIOT_Project_Flowcharts_Editable.pptx'),
    [string]$RenderDirectory = (Join-Path $PSScriptRoot 'tmp/pptx/powerpoint-renders'),
    [switch]$EditSmokeTest
)
# Render using installed Microsoft PowerPoint. Optional edits affect a copy only.
$ErrorActionPreference = 'Stop'
$deckPath = (Resolve-Path -LiteralPath $PresentationPath).Path
$null = New-Item -ItemType Directory -Path $RenderDirectory -Force
$renderPath = (Resolve-Path -LiteralPath $RenderDirectory).Path
$wasRunning = $null -ne (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
$pptApp = $null
$pptDeck = $null
try {
    $pptApp = New-Object -ComObject PowerPoint.Application
    $pptDeck = $pptApp.Presentations.Open($deckPath, -1, 0, 0)
    if ($pptDeck.Slides.Count -ne 38) { throw 'Expected 38 slides' }
    for ($slideNumber = 1; $slideNumber -le $pptDeck.Slides.Count; $slideNumber++) {
        $imagePath = Join-Path $renderPath ('slide-{0:D2}.png' -f $slideNumber)
        $pptDeck.Slides.Item($slideNumber).Export($imagePath, 'PNG', 1920, 1080)
        Write-Output "PowerPoint rendered slide $slideNumber"
    }
    $pptDeck.Close()
    $pptDeck = $null
    if ($EditSmokeTest) {
        $copyPath = Join-Path $renderPath 'edit-smoke-test.pptx'
        Copy-Item -LiteralPath $deckPath -Destination $copyPath
        $pptDeck = $pptApp.Presentations.Open($copyPath, 0, 0, 0)
        $node = $pptDeck.Slides.Item(26).Shapes.Item('F22 node a')
        $originalText = $node.TextFrame.TextRange.Text
        $node.TextFrame.TextRange.Text = $originalText + ' EDIT TEST'
        if ($node.TextFrame.TextRange.Text -notlike '*EDIT TEST*') { throw 'Node text edit failed' }
        $node.TextFrame.TextRange.Text = $originalText
        $arrow = $pptDeck.Slides.Item(26).Shapes.Item('F22 edge 01')
        if ($arrow.Nodes.Count -lt 2) { throw 'Arrow has no editable path nodes' }
        $points = $arrow.Nodes.Item(1).Points
        $row = $points.GetLowerBound(0)
        $column = $points.GetLowerBound(1)
        $originalX = [single]$points.GetValue($row, $column)
        $originalY = [single]$points.GetValue($row, ($column + 1))
        $arrow.Nodes.SetPosition(1, ($originalX + 1), $originalY)
        $arrow.Nodes.SetPosition(1, $originalX, $originalY)
        $tableShape = $null
        foreach ($candidateShape in $pptDeck.Slides.Item(35).Shapes) {
            if ($candidateShape.HasTable -eq -1) { $tableShape = $candidateShape; break }
        }
        if ($null -eq $tableShape) { throw 'Native table missing' }
        $cell = $tableShape.Table.Cell(2, 2).Shape.TextFrame.TextRange
        $originalCell = $cell.Text
        $cell.Text = 'EDIT TEST'
        if ($cell.Text -ne 'EDIT TEST') { throw 'Table edit failed' }
        $cell.Text = $originalCell
        $pptDeck.Save()
        $pptDeck.Close()
        $pptDeck = $pptApp.Presentations.Open($copyPath, -1, 0, 0)
        if ($pptDeck.Slides.Item(26).Shapes.Item('F22 node a').TextFrame.TextRange.Text -ne $originalText) {
            throw 'Text did not survive save/reopen'
        }
        Write-Output 'PASS: PowerPoint text edit, arrow-point edit, table edit and save/reopen'
    }
} finally {
    if ($null -ne $pptDeck) { $pptDeck.Close() }
    if ($null -ne $pptApp -and -not $wasRunning) { $pptApp.Quit() }
}
